import json
import pathlib
import sys
import unittest
from urllib.parse import parse_qs, urlparse

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from carriers.fedex import (
    COMMERCIAL_INVOICE,
    ELECTRONIC_TRADE_DOCUMENTS,
    FedExAPIError,
    FedExClient,
    FedExConfig,
    FedExValidationError,
    attach_pre_shipment_documents,
    extract_uploaded_document_id,
    uploaded_document_reference,
)
from carriers._core.retry import RetryPolicy
from carriers._core.transport import HttpResponse


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.closed = False

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def json_response(status, payload, headers=None):
    response_headers = {"Content-Type": "application/json"}
    if headers:
        response_headers.update(headers)
    return HttpResponse(status, response_headers, json.dumps(payload))


class FedExClientTests(unittest.TestCase):
    def config(self):
        return FedExConfig(
            client_id="client-id",
            client_secret="client-secret",
            base_url="https://example.test",
            document_base_url="https://documents.example.test",
            account_number="123456789",
        )

    def test_oauth_token_is_requested_and_cached(self):
        transport = FakeTransport(
            [
                json_response(
                    200,
                    {
                        "access_token": "token-1",
                        "token_type": "bearer",
                        "expires_in": 3600,
                        "scope": "CXS",
                    },
                )
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        token = client.get_access_token()
        cached = client.get_access_token()

        self.assertEqual(token.value, "token-1")
        self.assertIs(token, cached)
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://example.test/oauth/token")
        self.assertEqual(
            request["headers"]["Content-Type"], "application/x-www-form-urlencoded"
        )
        form = parse_qs(request["body"].decode("utf-8"))
        self.assertEqual(form["grant_type"], ["client_credentials"])
        self.assertEqual(form["client_id"], ["client-id"])
        self.assertEqual(form["client_secret"], ["client-secret"])

    def test_config_from_env_file_accepts_local_aliases(self):
        env_path = self._tmp_env(
            "FEDEX_CLIENT=client-from-file\n"
            "FEDEX_SECRET=secret-from-file\n"
            "FEDEX_ACCOUNT=account-from-file\n"
            "FEDEX_ENVIRONMENT=production\n"
        )

        config = FedExConfig.from_env(env_file=env_path)

        self.assertEqual(config.client_id, "client-from-file")
        self.assertEqual(config.client_secret, "secret-from-file")
        self.assertEqual(config.account_number, "account-from-file")
        self.assertEqual(config.environment, "production")
        self.assertEqual(config.resolved_base_url, "https://apis.fedex.com")
        self.assertEqual(config.resolved_document_base_url, "https://documentapi.prod.fedex.com")

    def test_track_request_sends_bearer_token_and_payload(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "token-1", "expires_in": 3600}),
                json_response(200, {"output": {"completeTrackResults": []}}),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        response = client.track_by_tracking_numbers(["123", "456"])

        self.assertEqual(response.data["output"]["completeTrackResults"], [])
        request = transport.requests[1]
        self.assertEqual(request["url"], "https://example.test/track/v1/trackingnumbers")
        self.assertEqual(request["headers"]["Authorization"], "Bearer token-1")
        payload = json.loads(request["body"].decode("utf-8"))
        self.assertFalse(payload["includeDetailedScans"])
        self.assertEqual(
            payload["trackingInfo"],
            [
                {"trackingNumberInfo": {"trackingNumber": "123"}},
                {"trackingNumberInfo": {"trackingNumber": "456"}},
            ],
        )

    def test_query_params_are_encoded(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "token-1", "expires_in": 3600}),
                json_response(200, {"ok": True}),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        client.get("/example", query={"a": "one two", "b": ["x", "y"]})

        parsed = urlparse(transport.requests[1]["url"])
        self.assertEqual(parsed.path, "/example")
        self.assertEqual(parse_qs(parsed.query), {"a": ["one two"], "b": ["x", "y"]})

    def test_validation_errors_include_fedex_messages(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "token-1", "expires_in": 3600}),
                json_response(
                    400,
                    {"errors": [{"code": "BAD.REQUEST", "message": "Invalid payload"}]},
                    headers={"x-customer-transaction-id": "txn-1"},
                ),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        with self.assertRaises(FedExValidationError) as raised:
            client.rate_quotes({"bad": True})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.transaction_id, "txn-1")
        self.assertIn("BAD.REQUEST: Invalid payload", str(raised.exception))

    def test_non_json_error_still_raises(self):
        transport = FakeTransport(
            [HttpResponse(500, {"Content-Type": "text/plain"}, "server exploded")]
        )
        # Retry is exercised in tests/core; here we want the raise, not
        # three attempts against a one-response transport.
        client = FedExClient(
            self.config(), transport=transport, retry_policy=RetryPolicy.disabled()
        )

        with self.assertRaises(FedExAPIError):
            client.request("GET", "/status", authenticated=False)

    def test_context_manager_closes_transport(self):
        transport = FakeTransport([])
        with FedExClient(self.config(), transport=transport):
            pass
        self.assertTrue(transport.closed)

    def test_upload_commercial_invoice_uses_document_api_multipart_contract(self):
        transport = FakeTransport(
            [
                json_response(200, {"access_token": "token-1", "expires_in": 3600}),
                json_response(
                    201,
                    {"output": {"meta": {"docId": "090493e181586308"}}},
                    headers={"x-customer-transaction-id": "txn-1"},
                ),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        response = client.upload_commercial_invoice(
            b"%PDF-1.4 invoice\n",
            filename="commercial-invoice.pdf",
            content_type="application/pdf",
            origin_country_code="US",
            destination_country_code="CA",
            carrier_code="FDXE",
            transaction_id="txn-1",
        )

        self.assertEqual(client.uploaded_document_id(response), "090493e181586308")
        request = transport.requests[1]
        self.assertEqual(
            request["url"],
            "https://documents.example.test/documents/v1/etds/upload",
        )
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["headers"]["Authorization"], "Bearer token-1")
        self.assertTrue(
            request["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
        )
        body = request["body"].decode("utf-8")
        self.assertIn('name="document"', body)
        self.assertIn('"workflowName":"ETDPreshipment"', body)
        self.assertIn('"carrierCode":"FDXE"', body)
        self.assertIn('"shipDocumentType":"COMMERCIAL_INVOICE"', body)
        self.assertIn('"originCountryCode":"US"', body)
        self.assertIn('"destinationCountryCode":"CA"', body)
        self.assertIn('name="attachment"; filename="commercial-invoice.pdf"', body)
        self.assertIn("Content-Type: application/pdf", body)
        self.assertIn("%PDF-1.4 invoice", body)

    def test_uploaded_document_reference_shape_for_ship_api(self):
        reference = uploaded_document_reference(
            document_id="090493e181586308",
            document_type=COMMERCIAL_INVOICE,
            document_reference="job-123",
            description="Commercial Invoice",
        )

        self.assertEqual(
            reference,
            {
                "documentType": "COMMERCIAL_INVOICE",
                "documentId": "090493e181586308",
                "documentReference": "job-123",
                "description": "Commercial Invoice",
            },
        )

    def test_attach_pre_shipment_documents_adds_etd_detail_without_mutating_input(self):
        original = {
            "requestedShipment": {
                "shipmentSpecialServices": {
                    "specialServiceTypes": ["BROKER_SELECT_OPTION"]
                }
            }
        }
        reference = uploaded_document_reference(document_id="doc-1")

        payload = attach_pre_shipment_documents(
            original,
            [reference],
            requested_document_types=[COMMERCIAL_INVOICE],
        )

        services = payload["requestedShipment"]["shipmentSpecialServices"]
        self.assertEqual(
            services["specialServiceTypes"],
            ["BROKER_SELECT_OPTION", ELECTRONIC_TRADE_DOCUMENTS],
        )
        self.assertEqual(services["etdDetail"]["attachedDocuments"], [reference])
        self.assertEqual(services["etdDetail"]["requestedDocumentTypes"], [COMMERCIAL_INVOICE])
        self.assertNotIn(
            ELECTRONIC_TRADE_DOCUMENTS,
            original["requestedShipment"]["shipmentSpecialServices"]["specialServiceTypes"],
        )

    def test_extract_uploaded_document_id_accepts_fedex_upload_response(self):
        self.assertEqual(
            extract_uploaded_document_id(
                {"output": {"meta": {"docId": "090493e181586308"}}}
            ),
            "090493e181586308",
        )

    def _tmp_env(self, content):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", delete=False)
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))
        with handle:
            handle.write(content)
        return handle.name


if __name__ == "__main__":
    unittest.main()
