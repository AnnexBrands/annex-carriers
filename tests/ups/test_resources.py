"""Tests for the UPS families the SDK did not previously reach.

Eight of nineteen Postman collections had methods before this change; these
cover the other eleven, plus the namespaced surface itself.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
from urllib.parse import parse_qs, urlparse

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from carriers.ups import (
    UPSClient,
    UPSConfig,
    build_customs_detail_request,
    build_landed_cost_request,
    build_metadata_field,
    build_metadata_group,
    build_track_alert_subscription,
    extract_landed_cost_totals,
    extract_package_status,
    replace_op,
)
from support import FakeTransport, json_response


class UPSResourceTestCase(unittest.TestCase):
    def config(self, **overrides):
        values = dict(
            client_id="client-id",
            client_secret="client-secret",
            base_url="https://example.test",
            account_number="A1B2C3",
        )
        values.update(overrides)
        return UPSConfig(**values)

    def token(self):
        return json_response(200, {"access_token": "token-1", "expires_in": "14399"})

    def client(self, *responses, **config_overrides):
        transport = FakeTransport([self.token(), *responses])
        client = UPSClient(self.config(**config_overrides), transport=transport)
        return client, transport

    def last(self, transport):
        return transport.requests[-1]

    def body(self, transport):
        return json.loads(self.last(transport)["body"].decode("utf-8"))

    def path(self, transport):
        return urlparse(self.last(transport)["url"]).path

    def query(self, transport):
        return parse_qs(urlparse(self.last(transport)["url"]).query)


class LandedCostTests(UPSResourceTestCase):
    def test_quote_posts_to_landedcost_and_fills_commodity_ids(self):
        client, transport = self.client(json_response(200, {"shipment": {}}))

        client.trade.landed_cost(
            shipment_id="S1",
            import_country_code="GB",
            export_country_code="US",
            currency_code="GBP",
            items=[{"hsCode": "400932", "priceEach": "125", "quantity": 24}],
        )

        self.assertEqual(self.path(transport), "/api/landedcost/v1/quotes")
        payload = self.body(transport)
        self.assertEqual(payload["currencyCode"], "GBP")
        self.assertEqual(payload["shipment"]["importCountryCode"], "GB")
        # UPS requires a commodityId per item; the builder fills it in.
        self.assertEqual(payload["shipment"]["shipmentItems"][0]["commodityId"], "1")

    def test_builder_rejects_an_empty_commodity_list(self):
        with self.assertRaises(ValueError):
            build_landed_cost_request(
                shipment_id="S1",
                import_country_code="GB",
                export_country_code="US",
                items=[],
            )

    def test_totals_are_flattened(self):
        totals = extract_landed_cost_totals(
            {
                "currencyCode": "GBP",
                "shipment": {
                    "id": "S1",
                    "totalDuties": "10.00",
                    "totalTaxes": "5.00",
                    "totalLandedCost": "140.00",
                },
            }
        )
        self.assertEqual(totals["totalLandedCost"], "140.00")
        self.assertEqual(totals["shipmentId"], "S1")

    def test_totals_of_a_non_mapping_are_none(self):
        self.assertIsNone(extract_landed_cost_totals("nope"))


class CustomsDetailTests(UPSResourceTestCase):
    def test_required_fields_lookup_sends_lane_query(self):
        client, transport = self.client(json_response(200, {}))

        client.trade.customs_detail_fields(
            import_country_code="IN",
            export_country_code="US",
            commodity_codes=["400932", "610910"],
        )

        request = self.last(transport)
        self.assertEqual(request["method"], "GET")
        self.assertEqual(
            self.path(transport), "/api/trade/compliance/v2/content/fields/customs-detail"
        )
        query = self.query(transport)
        self.assertEqual(query["import_country_code"], ["IN"])
        self.assertEqual(query["commodity_codes"], ["400932,610910"])

    def test_submit_defaults_to_validate_and_uses_the_account_number(self):
        client, transport = self.client(json_response(200, {}))

        client.trade.submit_customs_detail(
            shipment_metadata=[
                build_metadata_group("IN-EXP-CSB", [build_metadata_field("CSBType", "3")])
            ]
        )

        payload = self.body(transport)
        self.assertEqual(payload["actionType"], "validate")
        self.assertEqual(payload["shipperNumber"], "A1B2C3")
        self.assertEqual(payload["shipmentMetaData"][0]["groupKey"], "IN-EXP-CSB")

    def test_save_requires_a_tracking_number(self):
        with self.assertRaises(ValueError):
            build_customs_detail_request(
                shipper_number="A1B2C3", shipment_metadata=[], action_type="save"
            )

    def test_unknown_action_type_is_rejected(self):
        with self.assertRaises(ValueError):
            build_customs_detail_request(
                shipper_number="A1B2C3", shipment_metadata=[], action_type="delete"
            )

    def test_regulation_sections_are_nested_under_the_field(self):
        field = build_metadata_field("ImportLicenseNumber", "123", regulation_sections=["Bio"])
        self.assertEqual(field["regulationSections"], [{"sectionKey": "Bio"}])


class ExportAssureTests(UPSResourceTestCase):
    def test_compliance_guidance_endpoint(self):
        client, transport = self.client(json_response(200, {}))
        client.trade.export_assure_compliance({"commodities": []})
        self.assertEqual(self.path(transport), "/api/brokerage/v1/importexport/exportassure")

    def test_interactive_description_endpoint(self):
        client, transport = self.client(json_response(200, {}))
        client.trade.export_assure_interactive({"description": "widgets"})
        self.assertEqual(self.path(transport), "/api/export-assure/v1/interactive")


class TrackAlertTests(UPSResourceTestCase):
    def test_standard_subscription_posts_the_destination(self):
        client, transport = self.client(json_response(200, {}))

        client.tracking.subscribe(
            ["1ZCIETST0111111114"],
            destination_url="https://hooks.example.test/ups",
            credential="s3cret",
        )

        self.assertEqual(
            self.path(transport), "/api/track/v1/subscription/standard/package"
        )
        payload = self.body(transport)
        self.assertEqual(payload["trackingNumberList"], ["1ZCIETST0111111114"])
        self.assertEqual(payload["destination"]["credential"], "s3cret")

    def test_enhanced_subscription_uses_the_enhanced_path(self):
        client, transport = self.client(json_response(200, {}))
        client.tracking.subscribe(
            ["1Z"], destination_url="https://x.test", credential="c", enhanced=True
        )
        self.assertEqual(
            self.path(transport), "/api/track/v1/subscription/enhanced/package"
        )

    def test_subscription_builder_requires_numbers_and_a_destination(self):
        with self.assertRaises(ValueError):
            build_track_alert_subscription([], destination_url="https://x", credential="c")
        with self.assertRaises(ValueError):
            build_track_alert_subscription(["1Z"], destination_url="", credential="c")

    def test_package_status_is_flattened_from_a_track_response(self):
        status = extract_package_status(
            {
                "trackResponse": {
                    "shipment": [
                        {
                            "inquiryNumber": "1Z1",
                            "package": [
                                {
                                    "trackingNumber": "1Z1",
                                    "activity": [
                                        {
                                            "date": "20260701",
                                            "time": "101500",
                                            "status": {
                                                "code": "011",
                                                "type": "I",
                                                "description": "Out for Delivery",
                                            },
                                        }
                                    ],
                                    "deliveryDate": [{"type": "SDD", "date": "20260702"}],
                                }
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual(status["statusDescription"], "Out for Delivery")
        self.assertEqual(status["deliveryDate"], "20260702")

    def test_package_status_handles_single_object_collapse(self):
        # UPS collapses single-element arrays to bare objects in some versions.
        status = extract_package_status(
            {
                "trackResponse": {
                    "shipment": {
                        "inquiryNumber": "1Z1",
                        "package": {"trackingNumber": "1Z1", "activity": []},
                    }
                }
            }
        )
        self.assertEqual(status["trackingNumber"], "1Z1")


class VisibilityTests(UPSResourceTestCase):
    def test_quantum_view_events(self):
        client, transport = self.client(json_response(200, {}))
        client.visibility.quantum_view_events({"QuantumViewRequest": {}})
        self.assertEqual(self.path(transport), "/api/quantumview/v2/events")

    def test_delivery_intercept_charges_include_the_tracking_number_in_the_path(self):
        client, transport = self.client(json_response(200, {}))
        client.visibility.intercept_charges("1Z1144YY0125887968", {"requestType": "UFD"})
        self.assertEqual(
            self.path(transport), "/api/deliverychange/v2/charges/1Z1144YY0125887968"
        )

    def test_delivery_defense_scores_an_address(self):
        client, transport = self.client(json_response(200, {"score": 900}))
        response = client.visibility.address_confidence(
            street="1173 CLARENDON DR", city="MARIETTA", state="GA", zip_code="30068"
        )
        self.assertEqual(
            self.path(transport), "/api/deliverydefense/external/v1.0/address/score"
        )
        self.assertEqual(self.body(transport)["zipCode"], "30068")
        self.assertEqual(response.data["score"], 900)


class DangerousGoodsTests(UPSResourceTestCase):
    def test_pre_notification(self):
        client, transport = self.client(json_response(200, {}))
        client.dangerous_goods.pre_notification({"PreNotificationRequest": {}})
        self.assertEqual(self.path(transport), "/api/dangerousgoods/v2/prenotification")


class PickupInfoTests(UPSResourceTestCase):
    def test_political_divisions_lookup(self):
        client, transport = self.client(json_response(200, {}))
        client.pickups.political_divisions("US")
        self.assertEqual(self.path(transport), "/api/pickup/v1/countries/US")

    def test_service_center_facilities(self):
        client, transport = self.client(json_response(200, {}))
        client.pickups.service_centers({"PickupGetServiceCenterFacilitiesRequest": {}})
        self.assertEqual(self.path(transport), "/api/pickup/v1/servicecenterlocations")


class ForwardingTests(UPSResourceTestCase):
    def test_paths_keep_the_upstream_spelling(self):
        client, transport = self.client(json_response(200, {}))
        client.forwarding.create_order({"shipper": {}})
        # UPS's own path spells it "fowarding"; correcting it 404s.
        self.assertEqual(self.path(transport), "/api/fowarding/v1/orders")

    def test_configured_headers_are_sent_on_every_call(self):
        client, transport = self.client(json_response(200, {}))
        client.forwarding.configure(business_guid="bg-1", client_id="cl-1")

        client.forwarding.create_shipment({"shipper": {}})

        headers = self.last(transport)["headers"]
        self.assertEqual(headers["X-BusinessGUID"], "bg-1")
        self.assertEqual(headers["X-ClientId"], "cl-1")

    def test_per_call_headers_override_the_configured_ones(self):
        client, transport = self.client(json_response(200, {}))
        client.forwarding.configure(business_guid="bg-1")
        client.forwarding.create_shipment({}, business_guid="bg-2")
        self.assertEqual(self.last(transport)["headers"]["X-BusinessGUID"], "bg-2")

    def test_update_order_date_sends_a_json_patch_and_the_typo_parameter(self):
        client, transport = self.client(json_response(200, {}))

        client.forwarding.update_order_date(
            [replace_op("/newDate", "2026-07-24")],
            shipper_account_number="123456789",
            order_number="3912088430001",
            old_date="2026-07-01",
        )

        request = self.last(transport)
        self.assertEqual(request["method"], "PATCH")
        self.assertEqual(json.loads(request["body"]), [
            {"op": "replace", "path": "/newDate", "value": "2026-07-24"}
        ])
        # UPS's query parameter really is spelled "shippper_account_numer".
        self.assertEqual(self.query(transport)["shippper_account_numer"], ["123456789"])

    def test_cancel_shipment_sends_a_delete_with_a_body(self):
        client, transport = self.client(json_response(200, {}))
        client.forwarding.cancel_shipment(
            {"shipperAccountNumber": "1", "shipmentNumber": "2"}
        )
        request = self.last(transport)
        self.assertEqual(request["method"], "DELETE")
        self.assertIn(b"shipmentNumber", request["body"])

    def test_reference_lookups_drop_unset_parameters(self):
        client, transport = self.client(json_response(200, {}))
        client.forwarding.cities(shipper_account_number="123", country="US")
        query = self.query(transport)
        self.assertEqual(sorted(query), ["country", "shipper_account_number"])

    def test_empty_patch_is_rejected_before_it_reaches_ups(self):
        client, _ = self.client(json_response(200, {}))
        with self.assertRaises(ValueError):
            client.forwarding.process_shipments([], shipper_account_number="1")


class OAuthTests(UPSResourceTestCase):
    def test_authorization_url_includes_client_and_redirect(self):
        client, _ = self.client(redirect_uri="https://app.test/cb")
        url = client.oauth.authorization_url(state="xyz")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/security/v1/oauth/authorize")
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["redirect_uri"], ["https://app.test/cb"])
        self.assertEqual(query["state"], ["xyz"])

    def test_authorization_url_requires_a_redirect_uri(self):
        client, _ = self.client()
        with self.assertRaises(ValueError):
            client.oauth.authorization_url()

    def test_code_exchange_installs_the_token_on_the_client(self):
        transport = FakeTransport(
            [
                json_response(
                    200,
                    {
                        "access_token": "user-token",
                        "expires_in": "3600",
                        "refresh_token": "r1",
                    },
                )
            ]
        )
        client = UPSClient(self.config(redirect_uri="https://app.test/cb"), transport=transport)

        token = client.oauth.exchange_authorization_code("the-code")

        self.assertEqual(token.value, "user-token")
        self.assertEqual(token.refresh_token, "r1")
        self.assertEqual(client.get_access_token().value, "user-token")
        body = transport.requests[-1]["body"].decode()
        self.assertIn("grant_type=authorization_code", body)
        self.assertIn("code=the-code", body)

    def test_refresh_uses_the_refresh_endpoint(self):
        transport = FakeTransport(
            [json_response(200, {"access_token": "t2", "expires_in": "3600"})]
        )
        client = UPSClient(self.config(), transport=transport)

        client.oauth.refresh("r1")

        self.assertTrue(transport.requests[-1]["url"].endswith("/security/v1/oauth/refresh"))


class NamespaceTests(UPSResourceTestCase):
    def test_namespaces_are_created_once_per_client(self):
        client, _ = self.client()
        self.assertIs(client.rating, client.rating)

    def test_namespaces_are_not_shared_between_clients(self):
        first, _ = self.client()
        second, _ = self.client()
        self.assertIsNot(first.rating, second.rating)

    def test_flat_methods_and_namespaces_hit_the_same_endpoint(self):
        flat_client, flat_transport = self.client(json_response(200, {}))
        flat_client.rate({"RateRequest": {}})

        ns_client, ns_transport = self.client(json_response(200, {}))
        ns_client.rating.rate({"RateRequest": {}})

        self.assertEqual(self.path(flat_transport), self.path(ns_transport))


if __name__ == "__main__":
    unittest.main()
