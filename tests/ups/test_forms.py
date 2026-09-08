"""InternationalForms builders — the customs half of a UPS ship request.

Pure builders, so these are pure assertions: no transport, no client, no
credentials. Nothing in this file can reach UPS even if credentials were
present, which is the property that makes it safe to exercise the production
lane's payload shape.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from carriers.ups import (
    EEI_EXEMPTION,
    EEI_FILED_BY_SHIPPER,
    EEI_FILED_BY_UPS,
    EEI_PRE_DEPARTURE_ITN,
    attach_international_forms,
    attach_paperless_documents,
    build_eei_filing_option,
    build_invoice_form,
    build_product,
)


def a_product(**overrides):
    defaults = dict(description="Bronze sculpture", quantity=2, unit_value=300.0)
    defaults.update(overrides)
    return build_product(**defaults)


class ProductTests(unittest.TestCase):
    def test_the_unit_block_carries_count_and_per_unit_value(self):
        product = a_product()
        self.assertEqual(product["Unit"]["Number"], "2")
        self.assertEqual(product["Unit"]["Value"], "300.00")
        self.assertEqual(product["Unit"]["UnitOfMeasurement"]["Code"], "PCS")

    def test_optional_fields_are_absent_rather_than_blank(self):
        product = a_product()
        for key in ("CommodityCode", "OriginCountryCode", "ProductWeight"):
            self.assertNotIn(key, product)

    def test_weight_rides_when_known(self):
        product = a_product(weight=18.0)
        self.assertEqual(product["ProductWeight"]["Weight"], "18")
        self.assertEqual(product["ProductWeight"]["UnitOfMeasurement"]["Code"], "LBS")

    def test_the_origin_country_is_upper_cased(self):
        self.assertEqual(a_product(origin_country_code="de")["OriginCountryCode"], "DE")

    def test_a_zero_weight_is_omitted_rather_than_sent_as_zero(self):
        # `0 == None` is False, so a truthiness test is the only one that keeps
        # "Weight": "0" — which UPS rejects — off the wire.
        self.assertNotIn("ProductWeight", a_product(weight=0))
        self.assertNotIn("ProductWeight", a_product(weight=0.0))

    def test_a_non_numeric_value_is_refused_rather_than_stringified(self):
        # The old fallback put "Value": "None" on the wire: a declaration UPS
        # cannot read and nobody can audit.
        with self.assertRaises(ValueError):
            a_product(unit_value=None)

    def test_the_description_is_capped_at_the_ups_limit(self):
        product = a_product(description="x" * 200)
        self.assertEqual(len(product["Description"]), 35)


class EeiFilingOptionTests(unittest.TestCase):
    def test_filing_codes_match_the_ups_shipping_schema(self):
        # Shipping.yaml: 1 = shipper filed, 2 = AES Direct, 3 = UPS filed.
        # Assert the literal wire values, independently of our constants.
        self.assertEqual(EEI_FILED_BY_SHIPPER, "1")
        self.assertEqual(EEI_FILED_BY_UPS, "3")
        self.assertEqual(build_eei_filing_option(itn="X20260824123456"), {
            "Code": "1",
            "ShipperFiled": {"Code": "A", "PreDepartureITNNumber": "X20260824123456"},
        })
        self.assertEqual(build_eei_filing_option(exemption_legend="30.36"), {
            "Code": "1",
            "ShipperFiled": {"Code": "B", "ExemptionLegend": "30.36"},
        })

    def test_an_itn_is_cited_as_a_pre_departure_number(self):
        option = build_eei_filing_option(itn="X20260824123456")
        self.assertEqual(option["Code"], EEI_FILED_BY_SHIPPER)
        self.assertEqual(option["ShipperFiled"]["Code"], EEI_PRE_DEPARTURE_ITN)
        self.assertEqual(
            option["ShipperFiled"]["PreDepartureITNNumber"], "X20260824123456"
        )

    def test_an_exemption_is_cited_as_a_legend(self):
        option = build_eei_filing_option(exemption_legend="NOEEI 30.37(a)")
        self.assertEqual(option["ShipperFiled"]["Code"], EEI_EXEMPTION)
        self.assertEqual(option["ShipperFiled"]["ExemptionLegend"], "NOEEI 30.37(a)")

    def test_an_itn_outranks_an_exemption_when_both_arrive(self):
        option = build_eei_filing_option(
            itn="X20260824123456", exemption_legend="NOEEI 30.37(a)"
        )
        shipper_filed = option["ShipperFiled"]
        self.assertIn("PreDepartureITNNumber", shipper_filed)
        # Claiming an exemption alongside proof the filing happened would be
        # two contradictory statements on one shipment.
        self.assertNotIn("ExemptionLegend", shipper_filed)

    def test_neither_is_a_refusal_rather_than_an_empty_block(self):
        with self.assertRaises(ValueError):
            build_eei_filing_option()

    def test_a_shipment_reference_rides_when_given(self):
        option = build_eei_filing_option(
            exemption_legend="NOEEI 30.37(a)", shipment_reference="INV-1"
        )
        self.assertEqual(
            option["ShipperFiled"]["EEIShipmentReferenceNumber"], "INV-1"
        )


class InvoiceFormTests(unittest.TestCase):
    def test_a_plain_invoice_is_form_type_01(self):
        form = build_invoice_form(
            products=[a_product()], currency_code="usd", reason_for_export="SALE"
        )
        self.assertEqual(form["FormType"], "01")
        self.assertEqual(form["CurrencyCode"], "USD")
        self.assertEqual(form["ReasonForExport"], "SALE")
        self.assertEqual(len(form["Product"]), 1)

    def test_an_export_filing_adds_the_eei_form_type(self):
        form = build_invoice_form(
            products=[a_product()],
            currency_code="USD",
            reason_for_export="SALE",
            eei_filing_option=build_eei_filing_option(exemption_legend="NOEEI 30.37(a)"),
        )
        self.assertEqual(form["FormType"], ["11", "01"])
        self.assertIn("EEIFilingOption", form)

    def test_optional_header_fields_are_omitted_rather_than_blank(self):
        form = build_invoice_form(
            products=[a_product()], currency_code="USD", reason_for_export="SALE"
        )
        for key in ("InvoiceNumber", "InvoiceDate", "TermsOfShipment",
                    "DeclarationStatement", "Contacts", "EEIFilingOption"):
            self.assertNotIn(key, form)

    def test_a_declaration_with_no_products_is_refused(self):
        with self.assertRaises(ValueError):
            build_invoice_form(products=[], currency_code="USD", reason_for_export="SALE")

    def test_the_caller_s_forms_mapping_is_not_aliased_into_the_payload(self):
        form = build_invoice_form(
            products=[a_product()], currency_code="USD", reason_for_export="SALE"
        )
        attached = attach_international_forms(
            {"ShipmentRequest": {"Shipment": {}}}, form
        )
        forms = attached["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"
        ]
        forms["Product"][0]["Description"] = "changed"
        # A shallow copy would have mutated the caller's form here.
        self.assertEqual(form["Product"][0]["Description"], "Bronze sculpture")

    def test_the_products_are_copied_not_aliased(self):
        product = a_product()
        form = build_invoice_form(
            products=[product], currency_code="USD", reason_for_export="SALE"
        )
        form["Product"][0]["Description"] = "changed"
        self.assertEqual(product["Description"], "Bronze sculpture")


class AttachInternationalFormsTests(unittest.TestCase):
    def payload(self):
        return {"ShipmentRequest": {"Shipment": {"Service": {"Code": "08"}}}}

    def forms_of(self, payload):
        return payload["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"
        ]

    def test_the_declaration_lands_under_shipment_service_options(self):
        form = build_invoice_form(
            products=[a_product()], currency_code="USD", reason_for_export="SALE"
        )
        attached = attach_international_forms(self.payload(), form)
        self.assertEqual(self.forms_of(attached)["FormType"], "01")

    def test_the_input_payload_is_not_mutated(self):
        original = self.payload()
        attach_international_forms(
            original,
            build_invoice_form(
                products=[a_product()], currency_code="USD", reason_for_export="SALE"
            ),
        )
        self.assertNotIn("ShipmentServiceOptions", original["ShipmentRequest"]["Shipment"])

    def test_the_declaration_and_an_uploaded_document_compose(self):
        # The whole point: our rendered invoice ("07") rides beside the
        # declaration ("01") instead of replacing it.
        declared = attach_international_forms(
            self.payload(),
            build_invoice_form(
                products=[a_product()], currency_code="USD", reason_for_export="SALE"
            ),
        )
        final = attach_paperless_documents(declared, ["DOC-1"])
        forms = self.forms_of(final)
        self.assertEqual(forms["FormType"], ["01", "07"])
        self.assertEqual(forms["UserCreatedForm"]["DocumentID"], ["DOC-1"])
        self.assertEqual(forms["ReasonForExport"], "SALE")

    def test_it_composes_in_the_other_order_too(self):
        documented = attach_paperless_documents(self.payload(), ["DOC-1"])
        final = attach_international_forms(
            documented,
            build_invoice_form(
                products=[a_product()], currency_code="USD", reason_for_export="SALE"
            ),
        )
        forms = self.forms_of(final)
        self.assertEqual(forms["FormType"], ["07", "01"])
        self.assertEqual(forms["UserCreatedForm"]["DocumentID"], ["DOC-1"])

    def test_an_eei_declaration_composes_with_a_document(self):
        declared = attach_international_forms(
            self.payload(),
            build_invoice_form(
                products=[a_product()],
                currency_code="USD",
                reason_for_export="SALE",
                eei_filing_option=build_eei_filing_option(
                    exemption_legend="NOEEI 30.37(a)"
                ),
            ),
        )
        forms = self.forms_of(attach_paperless_documents(declared, ["DOC-1"]))
        self.assertEqual(forms["FormType"], ["11", "01", "07"])


class DefensiveDocumentIdTests(unittest.TestCase):
    """#693: a mis-read upload response must not become a phantom reference."""

    def payload(self):
        return {"ShipmentRequest": {"Shipment": {}}}

    def test_a_blank_document_id_is_refused(self):
        for bad in ("", "   ", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as raised:
                    attach_paperless_documents(self.payload(), [bad])
                self.assertIn("empty DocumentID", str(raised.exception))

    def test_a_blank_among_good_ids_is_still_refused(self):
        with self.assertRaises(ValueError):
            attach_paperless_documents(self.payload(), ["DOC-1", ""])

    def test_no_ids_at_all_is_refused(self):
        with self.assertRaises(ValueError):
            attach_paperless_documents(self.payload(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
