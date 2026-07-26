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

    def test_repr_never_exposes_secrets(self):
        config = FedExConfig(
            client_id="cid-visible",
            client_secret="SECRET-VALUE",
            child_secret="CHILD-SECRET",
        )
        shown = repr(config)
        self.assertNotIn("SECRET-VALUE", shown)
        self.assertNotIn("CHILD-SECRET", shown)
        self.assertIn("cid-visible", shown)

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
        # Retry is exercised in tests/core; here we want the raise.
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

    def test_cancel_endpoints_use_put(self):
        transport = FakeTransport(
            [
                json_response(
                    200,
                    {"access_token": "token-1", "token_type": "bearer",
                     "expires_in": 3600, "scope": "CXS"},
                ),
                json_response(200, {"output": {"cancelledShipment": True}}),
                json_response(200, {"output": {"pickupConfirmationCode": "1"}}),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        client.cancel_shipment({"trackingNumber": "794000000000"})
        client.cancel_pickup({"pickupConfirmationCode": "1"})

        ship_cancel, pickup_cancel = transport.requests[1:]
        self.assertEqual(ship_cancel["method"], "PUT")
        self.assertEqual(ship_cancel["url"], "https://example.test/ship/v1/shipments/cancel")
        self.assertEqual(pickup_cancel["method"], "PUT")
        self.assertEqual(pickup_cancel["url"], "https://example.test/pickup/v1/pickups/cancel")

    def _token(self):
        return json_response(
            200,
            {"access_token": "token-1", "token_type": "bearer",
             "expires_in": 3600, "scope": "CXS"},
        )

    def _ship_payload(self):
        return {
            "labelResponseOptions": "URL_ONLY",
            "accountNumber": {"value": "123456789"},
            "requestedShipment": {
                "serviceType": "FEDEX_GROUND",
                "shipper": {"address": {"postalCode": "30062", "countryCode": "US"}},
                "recipients": [{"address": {"postalCode": "M4N 3L6", "countryCode": "CA"}}],
                "labelSpecification": {"imageType": "PDF"},
                "shipmentSpecialServices": {
                    "specialServiceTypes": ["ELECTRONIC_TRADE_DOCUMENTS"],
                    "etdDetail": {"attachedDocuments": [{"documentId": "abc"}]},
                },
                "requestedPackageLineItems": [{"weight": {"units": "LB", "value": 7}}],
            },
        }

    def test_rate_request_derived_from_ship_payload(self):
        from carriers.fedex import rate_request_from_ship_payload

        ship = self._ship_payload()
        rate = rate_request_from_ship_payload(ship)

        shipment = rate["requestedShipment"]
        self.assertEqual(rate["accountNumber"], {"value": "123456789"})
        self.assertEqual(shipment["recipient"]["address"]["postalCode"], "M4N 3L6")
        self.assertNotIn("recipients", shipment)
        self.assertNotIn("labelSpecification", shipment)
        self.assertNotIn("etdDetail", shipment.get("shipmentSpecialServices", {}))
        self.assertEqual(shipment["rateRequestType"], ["ACCOUNT"])
        self.assertEqual(shipment["serviceType"], "FEDEX_GROUND")
        # service shopping drops the pinned service
        self.assertNotIn(
            "serviceType",
            rate_request_from_ship_payload(ship, all_services=True)["requestedShipment"],
        )
        # the source payload is untouched
        self.assertIn("recipients", ship["requestedShipment"])

    def test_rate_from_ship_payload_posts_rate_quotes(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {"output": {"rateReplyDetails": [
                        {"serviceType": "FEDEX_GROUND", "serviceName": "FedEx Ground",
                         "packagingType": "YOUR_PACKAGING",
                         "ratedShipmentDetails": [
                             {"rateType": "ACCOUNT", "totalNetCharge": 38.11, "currency": "USD"},
                             {"rateType": "LIST", "totalNetCharge": 61.42, "currency": "USD"},
                         ],
                         "commit": {"transitDays": {"description": "8 business days"}}},
                    ]}},
                ),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        response = client.rate_from_ship_payload(self._ship_payload())

        request = transport.requests[1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://example.test/rate/v1/rates/quotes")

        from carriers.fedex import extract_rate_options

        options = extract_rate_options(response.data)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["serviceType"], "FEDEX_GROUND")
        self.assertEqual(options[0]["totalNetCharge"], 38.11)  # ACCOUNT preferred over LIST
        self.assertEqual(options[0]["transitDays"], "8 business days")

    def test_validate_address_resolves_and_parses(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {"output": {"resolvedAddresses": [
                        {"classification": "RESIDENTIAL",
                         "streetLinesToken": ["22 BLYTH HILL RD"],
                         "city": "TORONTO", "stateOrProvinceCode": "ON",
                         "postalCode": "M4N 3L6", "countryCode": "CA",
                         "attributes": {"Matched": "true"}},
                    ]}},
                ),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        response = client.validate_address(
            {"streetLines": ["22 Blyth Hill Rd"], "city": "Toronto",
             "stateOrProvinceCode": "ON", "postalCode": "M4N 3L6", "countryCode": "CA"}
        )

        request = transport.requests[1]
        self.assertEqual(request["url"], "https://example.test/address/v1/addresses/resolve")
        body = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(len(body["addressesToValidate"]), 1)

        from carriers.fedex import first_resolved_address

        resolved = first_resolved_address(response.data)
        self.assertEqual(resolved["classification"], "RESIDENTIAL")
        self.assertTrue(resolved["matched"])

    def test_schedule_pickup_builds_payload_and_parses_confirmation(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {"output": {"pickupConfirmationCode": "PU123", "location": "MARA",
                                "message": "Pickup scheduled"}},
                ),
            ]
        )
        client = FedExClient(self.config(), transport=transport)

        response = client.schedule_pickup(
            pickup_contact={"personName": "Navis 23030GA", "phoneNumber": "4049997225"},
            pickup_address={"streetLines": ["1061 Triad Ct", "Suite 6"], "city": "Marietta",
                            "stateOrProvinceCode": "GA", "postalCode": "30062", "countryCode": "US"},
            ready_timestamp="2026-07-06T09:00:00Z",
            carrier_code="FDXG",
            package_count=1,
            total_weight_lb=7,
        )

        request = transport.requests[1]
        self.assertEqual(request["url"], "https://example.test/pickup/v1/pickups")
        body = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(body["associatedAccountNumber"], {"value": "123456789"})
        self.assertEqual(body["carrierCode"], "FDXG")
        self.assertEqual(body["totalWeight"], {"units": "LB", "value": 7.0})
        self.assertEqual(
            body["originDetail"]["pickupLocation"]["address"]["postalCode"], "30062"
        )

        from carriers.fedex import extract_pickup_confirmation

        confirmation = extract_pickup_confirmation(response.data)
        self.assertEqual(confirmation["confirmationCode"], "PU123")

    def test_decode_response_body_handles_gzip(self):
        import gzip

        from carriers._core.transport import decode_response_body

        body = json.dumps({"output": {"meta": {"docId": "abc"}}}).encode("utf-8")
        compressed = gzip.compress(body)
        # Honest header, mislabeled/missing header (magic-byte sniff), and plain.
        self.assertEqual(decode_response_body(compressed, {"Content-Encoding": "gzip"}), body.decode())
        self.assertEqual(decode_response_body(compressed, {}), body.decode())
        self.assertEqual(decode_response_body(body, {}), body.decode())

    def _tmp_env(self, content):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", delete=False)
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))
        with handle:
            handle.write(content)
        return handle.name


if __name__ == "__main__":
    unittest.main()
