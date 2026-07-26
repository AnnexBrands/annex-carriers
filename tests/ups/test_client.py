import base64
import json
import pathlib
import sys
import unittest
from urllib.parse import parse_qs, urlparse

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from carriers.ups import (
    COMMERCIAL_INVOICE,
    UPSAPIError,
    UPSClient,
    UPSConfig,
    UPSValidationError,
    attach_paperless_documents,
    extract_document_ids,
    extract_pickup_confirmation,
    extract_rate_options,
    first_candidate,
    rate_request_from_ship_payload,
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


class UPSClientTests(unittest.TestCase):
    def config(self):
        return UPSConfig(
            client_id="client-id",
            client_secret="client-secret",
            base_url="https://example.test",
            account_number="A1B2C3",
        )

    def _token(self):
        return json_response(
            200,
            {
                "access_token": "token-1",
                "token_type": "Bearer",
                "expires_in": "14399",
                "issued_at": "1685650384593",
                "status": "approved",
            },
        )

    def test_oauth_token_is_requested_and_cached(self):
        transport = FakeTransport([self._token()])
        client = UPSClient(self.config(), transport=transport)

        token = client.get_access_token()
        cached = client.get_access_token()

        self.assertEqual(token.value, "token-1")
        self.assertIs(token, cached)
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://example.test/security/v1/oauth/token")
        self.assertEqual(
            request["headers"]["Content-Type"], "application/x-www-form-urlencoded"
        )
        expected_basic = base64.b64encode(b"client-id:client-secret").decode("ascii")
        self.assertEqual(request["headers"]["Authorization"], f"Basic {expected_basic}")
        self.assertEqual(request["headers"]["x-merchant-id"], "A1B2C3")
        form = parse_qs(request["body"].decode("utf-8"))
        self.assertEqual(form["grant_type"], ["client_credentials"])

    def test_config_from_env_file_accepts_local_aliases(self):
        env_path = self._tmp_env(
            "UPS_CLIENT=client-from-file\n"
            "UPS_SECRET=secret-from-file\n"
            "UPS_ACCOUNT=account-from-file\n"
            "UPS_ENVIRONMENT=production\n"
        )

        config = UPSConfig.from_env(env_file=env_path)

        self.assertEqual(config.client_id, "client-from-file")
        self.assertEqual(config.client_secret, "secret-from-file")
        self.assertEqual(config.account_number, "account-from-file")
        self.assertEqual(config.environment, "production")
        self.assertEqual(config.resolved_base_url, "https://onlinetools.ups.com")

    def test_config_test_environment_maps_to_cie(self):
        env_path = self._tmp_env(
            "UPS_CLIENT_ID=id\nUPS_CLIENT_SECRET=secret\nUPS_ENVIRONMENT=test\n"
        )

        config = UPSConfig.from_env(env_file=env_path)

        self.assertEqual(config.environment, "cie")
        self.assertEqual(config.resolved_base_url, "https://wwwcie.ups.com")

    def test_track_request_sends_bearer_token_and_headers(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(200, {"trackResponse": {"shipment": []}}),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        response = client.track("1Z12345E0291980793", return_signature=True)

        self.assertEqual(response.data["trackResponse"]["shipment"], [])
        request = transport.requests[1]
        parsed = urlparse(request["url"])
        self.assertEqual(parsed.path, "/api/track/v1/details/1Z12345E0291980793")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "returnSignature": ["true"],
                "returnMilestones": ["false"],
                "returnPOD": ["false"],
            },
        )
        self.assertEqual(request["headers"]["Authorization"], "Bearer token-1")
        self.assertEqual(request["headers"]["transactionSrc"], "testing")
        self.assertEqual(len(request["headers"]["transId"]), 32)

    def test_query_params_are_encoded(self):
        transport = FakeTransport([self._token(), json_response(200, {"ok": True})])
        client = UPSClient(self.config(), transport=transport)

        client.get("/example", query={"a": "one two", "b": ["x", "y"]})

        parsed = urlparse(transport.requests[1]["url"])
        self.assertEqual(parsed.path, "/example")
        self.assertEqual(parse_qs(parsed.query), {"a": ["one two"], "b": ["x", "y"]})

    def test_validation_errors_include_ups_messages(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    400,
                    {
                        "response": {
                            "errors": [
                                {"code": "120100", "message": "Missing required field"}
                            ]
                        }
                    },
                    headers={"transId": "txn-1"},
                ),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        with self.assertRaises(UPSValidationError) as raised:
            client.rate({"bad": True})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.transaction_id, "txn-1")
        self.assertIn("120100: Missing required field", str(raised.exception))

    def test_non_json_error_still_raises(self):
        transport = FakeTransport(
            [HttpResponse(500, {"Content-Type": "text/plain"}, "server exploded")]
        )
        # Retry is exercised in tests/core; here we want the raise, not
        # three attempts against a one-response transport.
        client = UPSClient(
            self.config(), transport=transport, retry_policy=RetryPolicy.disabled()
        )

        with self.assertRaises(UPSAPIError):
            client.request("GET", "/status", authenticated=False)

    def test_context_manager_closes_transport(self):
        transport = FakeTransport([])
        with UPSClient(self.config(), transport=transport):
            pass
        self.assertTrue(transport.closed)

    def _ship_payload(self):
        return {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "LabelSpecification": {"LabelImageFormat": {"Code": "GIF"}},
                "Shipment": {
                    "Description": "SDK test",
                    "Shipper": {
                        "Name": "Shipper",
                        "ShipperNumber": "A1B2C3",
                        "Address": {
                            "AddressLine": ["2311 York Rd"],
                            "City": "Timonium",
                            "StateProvinceCode": "MD",
                            "PostalCode": "21093",
                            "CountryCode": "US",
                        },
                    },
                    "ShipTo": {
                        "Name": "Receiver",
                        "Address": {
                            "AddressLine": ["123 Main St"],
                            "City": "Alpharetta",
                            "StateProvinceCode": "GA",
                            "PostalCode": "30005",
                            "CountryCode": "US",
                        },
                    },
                    "PaymentInformation": {
                        "ShipmentCharge": {"Type": "01", "BillShipper": {"AccountNumber": "A1B2C3"}}
                    },
                    "Service": {"Code": "03", "Description": "Ground"},
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "07",
                            "UserCreatedForm": {"DocumentID": ["doc-1"]},
                        }
                    },
                    "Package": [
                        {
                            "Packaging": {"Code": "02"},
                            "PackageWeight": {
                                "UnitOfMeasurement": {"Code": "LBS"},
                                "Weight": "7",
                            },
                        }
                    ],
                },
            }
        }

    def test_rate_request_derived_from_ship_payload(self):
        ship = self._ship_payload()
        rate = rate_request_from_ship_payload(ship, negotiated_rates=True)

        shipment = rate["RateRequest"]["Shipment"]
        self.assertNotIn("PaymentInformation", shipment)
        self.assertEqual(
            shipment["PaymentDetails"]["ShipmentCharge"]["Type"], "01"
        )
        self.assertNotIn("Description", shipment)
        self.assertEqual(shipment["Package"][0]["PackagingType"], {"Code": "02"})
        self.assertNotIn("Packaging", shipment["Package"][0])
        self.assertNotIn("ShipmentServiceOptions", shipment)
        self.assertEqual(
            shipment["ShipmentRatingOptions"]["NegotiatedRatesIndicator"], "Y"
        )
        self.assertEqual(shipment["Service"]["Code"], "03")
        # service shopping drops the pinned service
        self.assertNotIn(
            "Service",
            rate_request_from_ship_payload(ship, all_services=True)["RateRequest"]["Shipment"],
        )
        # the source payload is untouched
        self.assertIn("PaymentInformation", ship["ShipmentRequest"]["Shipment"])
        self.assertIn("Packaging", ship["ShipmentRequest"]["Shipment"]["Package"][0])

    def test_rate_from_ship_payload_posts_rate_and_parses_options(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {
                        "RateResponse": {
                            "RatedShipment": [
                                {
                                    "Service": {"Code": "03", "Description": ""},
                                    "TotalCharges": {
                                        "CurrencyCode": "USD",
                                        "MonetaryValue": "61.42",
                                    },
                                    "NegotiatedRateCharges": {
                                        "TotalCharge": {
                                            "CurrencyCode": "USD",
                                            "MonetaryValue": "38.11",
                                        }
                                    },
                                    "GuaranteedDelivery": {
                                        "BusinessDaysInTransit": "3",
                                        "DeliveryByTime": "11:00 P.M.",
                                    },
                                }
                            ]
                        }
                    },
                ),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        response = client.rate_from_ship_payload(self._ship_payload())

        request = transport.requests[1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://example.test/api/rating/v2409/Rate")

        options = extract_rate_options(response.data)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["serviceCode"], "03")
        self.assertEqual(options[0]["serviceName"], "UPS Ground")  # filled from SERVICE_CODES
        self.assertEqual(options[0]["totalCharges"], "61.42")
        self.assertEqual(options[0]["negotiatedCharges"], "38.11")
        self.assertEqual(options[0]["daysInTransit"], "3")

    def test_shop_rates_uses_shop_request_option(self):
        transport = FakeTransport(
            [self._token(), json_response(200, {"RateResponse": {"RatedShipment": []}})]
        )
        client = UPSClient(self.config(), transport=transport)

        client.rate_from_ship_payload(self._ship_payload(), all_services=True)

        self.assertEqual(
            transport.requests[1]["url"], "https://example.test/api/rating/v2409/Shop"
        )

    def test_validate_address_builds_xav_request_and_parses(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {
                        "XAVResponse": {
                            "Response": {"ResponseStatus": {"Code": "1"}},
                            "ValidAddressIndicator": "",
                            "AddressClassification": {
                                "Code": "1",
                                "Description": "Commercial",
                            },
                            "Candidate": {
                                "AddressClassification": {
                                    "Code": "1",
                                    "Description": "Commercial",
                                },
                                "AddressKeyFormat": {
                                    "AddressLine": ["26601 ALISO CREEK RD"],
                                    "PoliticalDivision2": "ALISO VIEJO",
                                    "PoliticalDivision1": "CA",
                                    "PostcodePrimaryLow": "92656",
                                    "PostcodeExtendedLow": "5301",
                                    "CountryCode": "US",
                                },
                            },
                        }
                    },
                ),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        response = client.validate_address(
            {
                "AddressLine": ["26601 Aliso Creek Rd"],
                "City": "Aliso Viejo",
                "StateProvinceCode": "CA",
                "PostalCode": "92656-5301",
                "CountryCode": "US",
            }
        )

        request = transport.requests[1]
        self.assertEqual(request["url"], "https://example.test/api/addressvalidation/v2/3")
        body = json.loads(request["body"].decode("utf-8"))
        key_format = body["XAVRequest"]["AddressKeyFormat"]
        self.assertEqual(key_format["PoliticalDivision2"], "Aliso Viejo")
        self.assertEqual(key_format["PoliticalDivision1"], "CA")
        self.assertEqual(key_format["PostcodePrimaryLow"], "92656")
        self.assertEqual(key_format["PostcodeExtendedLow"], "5301")
        self.assertNotIn("City", key_format)

        candidate = first_candidate(response.data)
        self.assertEqual(candidate["classification"], "Commercial")
        self.assertEqual(candidate["city"], "ALISO VIEJO")
        self.assertEqual(candidate["postalCode"], "92656")

    def test_schedule_pickup_builds_payload_and_parses_prn(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    200,
                    {
                        "PickupCreationResponse": {
                            "Response": {"ResponseStatus": {"Code": "1"}},
                            "PRN": "2929602E9CP",
                            "RateStatus": {"Code": "01", "Description": "Rated"},
                            "RateResult": {
                                "CurrencyCode": "USD",
                                "GrandTotalOfAllCharge": "6.80",
                            },
                        }
                    },
                ),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        response = client.schedule_pickup(
            pickup_address={
                "CompanyName": "Annex Brands",
                "ContactName": "Pickup Manager",
                "AddressLine": "1061 Triad Ct",
                "City": "Marietta",
                "StateProvince": "GA",
                "PostalCode": "30062",
                "CountryCode": "US",
                "ResidentialIndicator": "N",
                "Phone": {"Number": "4049997225"},
            },
            pickup_date="20260706",
            pieces=[
                {
                    "ServiceCode": "001",
                    "Quantity": "1",
                    "DestinationCountryCode": "US",
                    "ContainerCode": "01",
                }
            ],
            total_weight_lb=7,
        )

        request = transport.requests[1]
        self.assertEqual(
            request["url"], "https://example.test/api/pickupcreation/v2409/pickup"
        )
        body = json.loads(request["body"].decode("utf-8"))
        creation = body["PickupCreationRequest"]
        self.assertEqual(creation["Shipper"]["Account"]["AccountNumber"], "A1B2C3")
        self.assertEqual(creation["PickupDateInfo"]["PickupDate"], "20260706")
        self.assertEqual(creation["TotalWeight"], {"Weight": "7", "UnitOfMeasurement": "LBS"})
        self.assertEqual(creation["PickupAddress"]["PostalCode"], "30062")

        confirmation = extract_pickup_confirmation(response.data)
        self.assertEqual(confirmation["prn"], "2929602E9CP")
        self.assertEqual(confirmation["grandTotal"], "6.80")

    def test_cancel_pickup_by_prn_uses_delete_with_header(self):
        transport = FakeTransport(
            [self._token(), json_response(200, {"PickupCancelResponse": {}})]
        )
        client = UPSClient(self.config(), transport=transport)

        client.cancel_pickup(prn="2929602E9CP")

        request = transport.requests[1]
        self.assertEqual(request["method"], "DELETE")
        self.assertEqual(request["url"], "https://example.test/api/shipments/v2409/pickup/02")
        self.assertEqual(request["headers"]["Prn"], "2929602E9CP")

    def test_void_shipment_uses_delete_with_tracking_numbers(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(200, {"VoidShipmentResponse": {}}),
                json_response(200, {"VoidShipmentResponse": {}}),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        client.void_shipment("1Z2220060290602143")
        client.void_shipment(
            "1Z2220060290602143",
            tracking_numbers=["1Z2220060291994175", "1Z2220060292690189"],
        )

        single, multiple = transport.requests[1:]
        self.assertEqual(single["method"], "DELETE")
        self.assertEqual(
            single["url"],
            "https://example.test/api/shipments/v2409/void/cancel/1Z2220060290602143",
        )
        parsed = urlparse(multiple["url"])
        self.assertEqual(
            parse_qs(parsed.query)["trackingnumber"],
            ['["1Z2220060291994175","1Z2220060292690189"]'],
        )

    def test_upload_paperless_document_encodes_base64_and_headers(self):
        transport = FakeTransport(
            [
                self._token(),
                json_response(
                    201,
                    {
                        "UploadResponse": {
                            "Response": {"ResponseStatus": {"Code": "1"}},
                            "FormsHistoryDocumentID": {
                                "DocumentID": ["2016-01-18-11.01.07.589501"]
                            },
                        }
                    },
                    headers={"transId": "txn-1"},
                ),
            ]
        )
        client = UPSClient(self.config(), transport=transport)

        response = client.upload_commercial_invoice(
            b"%PDF-1.4 invoice\n",
            filename="commercial-invoice.pdf",
        )

        self.assertEqual(
            client.uploaded_document_id(response), "2016-01-18-11.01.07.589501"
        )
        request = transport.requests[1]
        self.assertEqual(
            request["url"], "https://example.test/api/paperlessdocuments/v2/upload"
        )
        self.assertEqual(request["headers"]["ShipperNumber"], "A1B2C3")
        body = json.loads(request["body"].decode("utf-8"))
        upload = body["UploadRequest"]
        self.assertEqual(upload["ShipperNumber"], "A1B2C3")
        form = upload["UserCreatedForm"][0]
        self.assertEqual(form["UserCreatedFormFileName"], "commercial-invoice.pdf")
        self.assertEqual(form["UserCreatedFormFileFormat"], "pdf")
        self.assertEqual(form["UserCreatedFormDocumentType"], COMMERCIAL_INVOICE)
        self.assertEqual(
            base64.b64decode(form["UserCreatedFormFile"]), b"%PDF-1.4 invoice\n"
        )

    def test_delete_paperless_document_sends_identifier_headers(self):
        transport = FakeTransport(
            [self._token(), json_response(200, {"DeleteResponse": {}})]
        )
        client = UPSClient(self.config(), transport=transport)

        client.delete_paperless_document("2016-01-18-11.01.07.589501")

        request = transport.requests[1]
        self.assertEqual(request["method"], "DELETE")
        self.assertEqual(
            request["url"],
            "https://example.test/api/paperlessdocuments/v2/DocumentId/ShipperNumber",
        )
        self.assertEqual(request["headers"]["DocumentId"], "2016-01-18-11.01.07.589501")
        self.assertEqual(request["headers"]["ShipperNumber"], "A1B2C3")

    def test_attach_paperless_documents_adds_forms_without_mutating_input(self):
        original = {
            "ShipmentRequest": {
                "Shipment": {
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01",
                            "InvoiceNumber": "INV-1",
                        }
                    }
                }
            }
        }

        payload = attach_paperless_documents(original, ["doc-1", "doc-2"])

        forms = payload["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"
        ]
        self.assertEqual(forms["FormType"], ["01", "07"])
        self.assertEqual(forms["UserCreatedForm"]["DocumentID"], ["doc-1", "doc-2"])
        self.assertEqual(forms["InvoiceNumber"], "INV-1")
        self.assertEqual(
            original["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
                "InternationalForms"
            ]["FormType"],
            "01",
        )

    def test_extract_document_ids_handles_v1_single_object_collapse(self):
        self.assertEqual(
            extract_document_ids(
                {
                    "UploadResponse": {
                        "FormsHistoryDocumentID": {"DocumentID": "doc-1"}
                    }
                }
            ),
            ["doc-1"],
        )
        self.assertEqual(
            extract_document_ids(
                {
                    "UploadResponse": {
                        "FormsHistoryDocumentID": {"DocumentID": ["doc-1", "doc-2"]}
                    }
                }
            ),
            ["doc-1", "doc-2"],
        )

    def test_pickup_pending_status_requires_account_header(self):
        transport = FakeTransport(
            [self._token(), json_response(200, {"PickupPendingStatusResponse": {}})]
        )
        client = UPSClient(self.config(), transport=transport)

        client.pickup_pending_status()

        request = transport.requests[1]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(
            request["url"], "https://example.test/api/shipments/v2409/pickup/oncall"
        )
        self.assertEqual(request["headers"]["AccountNumber"], "A1B2C3")

    def _tmp_env(self, content):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", delete=False)
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))
        with handle:
            handle.write(content)
        return handle.name


if __name__ == "__main__":
    unittest.main()
