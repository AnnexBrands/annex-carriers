"""Tests for the FedEx namespaced surface and the routes corrected in 0.2.

The Ship API paths here are asserted against ``docs/specs/fedex/ship.json``:
cancel is PUT (0.1 sent POST) and validate lives under ``/packages/``
(0.1 sent ``/ship/v1/shipments/validate``). Neither had test coverage before,
which is how both survived.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
from urllib.parse import urlparse

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from carriers.fedex import (
    COMMERCIAL_INVOICE,
    POSTSHIPMENT_WORKFLOW,
    PRESHIPMENT_WORKFLOW,
    FedExClient,
    FedExConfig,
)
from carriers.fedex import endpoints
from support import FakeTransport, json_response

SPEC_DIR = _ROOT / "docs" / "specs" / "fedex"


class FedExResourceTestCase(unittest.TestCase):
    def config(self):
        return FedExConfig(
            client_id="client-id",
            client_secret="client-secret",
            base_url="https://example.test",
            document_base_url="https://documents.example.test",
            account_number="123456789",
        )

    def token(self):
        return json_response(200, {"access_token": "token-1", "expires_in": 3600})

    def client(self, *responses):
        transport = FakeTransport([self.token(), *responses])
        return FedExClient(self.config(), transport=transport), transport

    def last(self, transport):
        return transport.requests[-1]

    def path(self, transport):
        return urlparse(self.last(transport)["url"]).path


class ShipRoutesMatchTheSpecTests(unittest.TestCase):
    """Assert the endpoint constants against the bundled OpenAPI document."""

    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((SPEC_DIR / "ship.json").read_text(encoding="utf-8"))

    def assertRoute(self, path, method):
        operations = self.spec["paths"].get(path)
        self.assertIsNotNone(operations, f"{path} is not in ship.json")
        self.assertIn(method, operations, f"{path} does not accept {method.upper()}")

    def test_create_is_post(self):
        self.assertRoute(endpoints.SHIP_CREATE, "post")

    def test_cancel_is_put_not_post(self):
        self.assertRoute(endpoints.SHIP_CANCEL, "put")
        self.assertNotIn("post", self.spec["paths"][endpoints.SHIP_CANCEL])

    def test_validate_lives_under_packages(self):
        self.assertRoute(endpoints.SHIP_VALIDATE, "post")
        self.assertNotIn("/ship/v1/shipments/validate", self.spec["paths"])

    def test_results_and_tag_routes(self):
        self.assertRoute(endpoints.SHIP_RESULTS, "post")
        self.assertRoute(endpoints.SHIP_TAG_CREATE, "post")
        self.assertRoute("/ship/v1/shipments/tag/cancel/{shipmentid}", "put")


class DocumentRoutesMatchTheSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((SPEC_DIR / "upload-documents.json").read_text(encoding="utf-8"))

    def test_every_upload_route_exists(self):
        for path in (
            endpoints.ETD_UPLOAD,
            endpoints.ETD_MULTIUPLOAD,
            endpoints.ETD_ENCODED_MULTIUPLOAD,
            endpoints.LHS_IMAGE_UPLOAD,
        ):
            self.assertIn(path, self.spec["paths"], path)


class ShipResourceTests(FedExResourceTestCase):
    def test_cancel_uses_put(self):
        client, transport = self.client(json_response(200, {"output": {}}))
        client.ship.cancel({"trackingNumber": "1234"})
        self.assertEqual(self.last(transport)["method"], "PUT")
        self.assertEqual(self.path(transport), "/ship/v1/shipments/cancel")

    def test_flat_cancel_shipment_also_uses_put(self):
        client, transport = self.client(json_response(200, {}))
        client.cancel_shipment({"trackingNumber": "1234"})
        self.assertEqual(self.last(transport)["method"], "PUT")

    def test_validate_uses_the_packages_route(self):
        client, transport = self.client(json_response(200, {}))
        client.ship.validate({"requestedShipment": {}})
        self.assertEqual(self.path(transport), "/ship/v1/shipments/packages/validate")

    def test_cancel_tag_puts_the_shipment_id_in_the_path(self):
        client, transport = self.client(json_response(200, {}))
        client.ship.cancel_tag("SHIP 1", {"accountNumber": {}})
        self.assertEqual(self.last(transport)["method"], "PUT")
        self.assertEqual(self.path(transport), "/ship/v1/shipments/tag/cancel/SHIP%201")

    def test_async_results(self):
        client, transport = self.client(json_response(200, {}))
        client.ship.results({"jobId": "j1"})
        self.assertEqual(self.path(transport), "/ship/v1/shipments/results")


class TrackResourceTests(FedExResourceTestCase):
    def test_by_tracking_numbers_builds_the_track_payload(self):
        client, transport = self.client(json_response(200, {}))
        client.track.by_tracking_numbers(["1", "2"], include_detailed_scans=True)
        payload = json.loads(self.last(transport)["body"])
        self.assertTrue(payload["includeDetailedScans"])
        self.assertEqual(len(payload["trackingInfo"]), 2)

    def test_document_and_notification_routes(self):
        client, transport = self.client(json_response(200, {}), json_response(200, {}))
        client.track.documents({"trackDocumentDetail": {}})
        self.assertEqual(self.path(transport), "/track/v1/trackingdocuments")
        client.track.notifications({"trackingNumberInfo": {}})
        self.assertEqual(self.path(transport), "/track/v1/notifications")


class DocumentsResourceTests(FedExResourceTestCase):
    def test_upload_etd_posts_multipart_to_the_document_host(self):
        client, transport = self.client(
            json_response(200, {"output": {"meta": {"docId": "doc-1"}}})
        )

        response = client.documents.upload_etd(
            b"%PDF-1.4",
            filename="invoice.pdf",
            origin_country_code="US",
            destination_country_code="GB",
        )

        request = self.last(transport)
        self.assertTrue(request["url"].startswith("https://documents.example.test"))
        self.assertEqual(urlparse(request["url"]).path, "/documents/v1/etds/upload")
        self.assertTrue(request["headers"]["Content-Type"].startswith("multipart/form-data"))
        self.assertIn(b'filename="invoice.pdf"', request["body"])
        self.assertEqual(client.documents.document_id(response), "doc-1")

    def test_pre_shipment_upload_uses_the_preshipment_workflow(self):
        client, transport = self.client(json_response(200, {}))
        client.documents.upload_pre_shipment(
            b"%PDF", filename="ci.pdf", origin_country_code="US", destination_country_code="GB"
        )
        document = self._document_part(self.last(transport)["body"])
        self.assertEqual(document["workflowName"], PRESHIPMENT_WORKFLOW)
        self.assertNotIn("trackingNumber", document["meta"])

    def test_post_shipment_upload_carries_tracking_number_and_ship_date(self):
        # The distinction the local sandbox copy collapsed: booking through a
        # third party makes the integration structurally post-shipment.
        client, transport = self.client(json_response(200, {}))

        client.documents.upload_post_shipment(
            b"%PDF",
            filename="ci.pdf",
            origin_country_code="US",
            destination_country_code="GB",
            tracking_number="794123456789",
            shipment_date="2026-07-24",
        )

        document = self._document_part(self.last(transport)["body"])
        self.assertEqual(document["workflowName"], POSTSHIPMENT_WORKFLOW)
        self.assertEqual(document["meta"]["trackingNumber"], "794123456789")
        self.assertEqual(document["meta"]["shipmentDate"], "2026-07-24")
        self.assertEqual(document["carrierCode"], "FDXE")

    def test_post_shipment_upload_requires_the_tracking_number(self):
        client, _ = self.client(json_response(200, {}))
        with self.assertRaises(TypeError):
            client.documents.upload_post_shipment(
                b"%PDF",
                filename="ci.pdf",
                origin_country_code="US",
                destination_country_code="GB",
            )

    def test_image_upload_targets_the_lhs_route(self):
        client, transport = self.client(json_response(200, {}))
        client.documents.upload_images(
            {"name": "logo.png", "contentType": "image/png"}, b"\x89PNG", filename="logo.png"
        )
        self.assertEqual(
            urlparse(self.last(transport)["url"]).path, "/documents/v1/lhsimages/upload"
        )

    def test_reference_and_attach_produce_a_shipment_payload(self):
        client, _ = self.client()
        reference = client.documents.reference("doc-1")
        payload = client.documents.attach_to_shipment(
            {"requestedShipment": {}}, [reference]
        )
        etd = payload["requestedShipment"]["shipmentSpecialServices"]["etdDetail"]
        self.assertEqual(etd["attachedDocuments"][0]["documentId"], "doc-1")
        self.assertEqual(reference["documentType"], COMMERCIAL_INVOICE)

    def test_uploading_bytes_without_a_filename_is_rejected(self):
        client, _ = self.client(json_response(200, {}))
        with self.assertRaises(ValueError):
            client.documents.upload_etd(
                b"%PDF", origin_country_code="US", destination_country_code="GB"
            )

    @staticmethod
    def _document_part(body):
        """Pull the JSON ``document`` field back out of a multipart body."""
        text = body.decode("utf-8", errors="replace")
        start = text.index("{", text.index('name="document"'))
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : index + 1])
        raise AssertionError("no document part found")


class NamespaceTests(FedExResourceTestCase):
    def test_documents_namespace_exists(self):
        # The notebook reached for fx.documents.upload_etd and got an
        # AttributeError; it resolves now.
        client, _ = self.client()
        self.assertTrue(callable(client.documents.upload_etd))

    def test_namespaces_are_memoised_per_client(self):
        client, _ = self.client()
        self.assertIs(client.ship, client.ship)

    def test_locale_is_sent_as_a_header(self):
        client, transport = self.client(json_response(200, {}))
        client.rate.quotes({"accountNumber": {}}, locale="fr_FR")
        self.assertEqual(self.last(transport)["headers"]["X-locale"], "fr_FR")


class UnverifiedRoutesTests(unittest.TestCase):
    def test_unverified_set_is_declared_and_non_empty(self):
        # Provenance is tracked in code, not just prose: anything in this set
        # has not been checked against a spec or a live call.
        self.assertIn(endpoints.POSTAL_VALIDATE, endpoints.UNVERIFIED)
        self.assertNotIn(endpoints.SHIP_CREATE, endpoints.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
