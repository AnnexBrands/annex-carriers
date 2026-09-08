"""``InternationalForms`` builders — the customs half of a UPS ship request.

UPS carries the whole customs declaration inside
``Shipment.ShipmentServiceOptions.InternationalForms``. That one block does
several unrelated jobs depending on its ``FormType``:

===========  ====================================================
``"01"``     Invoice — the commercial invoice UPS generates
``"07"``     User-created forms — documents YOU uploaded (paperless)
``"11"``     EEI — the US export filing
===========  ====================================================

``documents.py`` already owns ``"07"``. This module owns the declaration:
the products, the money, the reason for export and the export filing.

**The two compose, and the order matters.** Build the invoice block first,
then let :func:`carriers.ups.attach_paperless_documents` add the uploaded
document — it sees the existing ``"01"`` and produces ``["01", "07"]``, which
is UPS's way of saying "here is the declaration, and here is the PDF that goes
with it". Asking UPS to *generate* an invoice when you have already rendered
one is how a shipment ends up with two.

Everything here is a pure builder over plain types — no domain objects, no
I/O, no environment. UPS wants its numbers as strings, so they are stringified
at the edge rather than by every caller.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Optional, Sequence

# --- FormType codes --------------------------------------------------------
#
# Deliberately NOT a full inventory of UPS's FormType table. ``documents.py``
# already exports UPS's *document-type* codes, where "003" means certificate of
# origin and "010" means packing list — a different numbering for a different
# field. Defining the form-type spellings of those same words here would put
# two constants with one name and two values in the package. Only the codes
# this module actually builds are named.

#: The commercial invoice declaration.
INVOICE = "01"
#: The US Electronic Export Information filing.
EEI = "11"

# FormType "07" (user-created forms) is owned by :mod:`carriers.ups.documents`
# as ``USER_CREATED_FORM`` and is deliberately not redefined here.

# --- EEI filing options ----------------------------------------------------

#: UPS files the EEI on the shipper's behalf (needs a power of attorney).
EEI_FILED_BY_UPS = "3"
#: The shipper filed it, or claims an exemption from filing.
EEI_FILED_BY_SHIPPER = "1"

#: Shipper-filed sub-codes. ``A`` cites a pre-departure ITN; ``B`` is the
#: exemption case with an ``ExemptionLegend``. Post-departure is code ``C``.
EEI_PRE_DEPARTURE_ITN = "A"
EEI_EXEMPTION = "B"

_DEFAULT_UNIT_OF_MEASURE = "PCS"
_DEFAULT_WEIGHT_UNIT = "LBS"


def build_product(
    *,
    description: str,
    quantity: Any,
    unit_value: Any,
    unit_of_measure: str = _DEFAULT_UNIT_OF_MEASURE,
    weight: Any = None,
    weight_unit: str = _DEFAULT_WEIGHT_UNIT,
    commodity_code: Optional[str] = None,
    origin_country_code: Optional[str] = None,
) -> dict[str, Any]:
    """One line of the declaration.

    ``unit_value`` is the price of a single unit, not the line total — UPS
    multiplies by ``Unit.Number`` itself, so passing a line total here silently
    over-declares the shipment by the quantity.
    """

    product: dict[str, Any] = {
        "Description": str(description or "")[:35],
        "Unit": {
            "Number": _text(quantity),
            "UnitOfMeasurement": {"Code": unit_of_measure},
            "Value": _money(unit_value),
        },
    }
    if commodity_code:
        product["CommodityCode"] = str(commodity_code)
    if origin_country_code:
        product["OriginCountryCode"] = str(origin_country_code).upper()
    # Truthiness, not `not in (None, "")`: `0 == None` is False, so a zero
    # weight slipped through as "Weight": "0", which UPS rejects. An unknown
    # weight and a zero weight both mean "do not send the block".
    if weight:
        product["ProductWeight"] = {
            "UnitOfMeasurement": {"Code": weight_unit},
            "Weight": _text(weight),
        }
    return product


def build_eei_filing_option(
    *,
    itn: Optional[str] = None,
    exemption_legend: Optional[str] = None,
    shipment_reference: Optional[str] = None,
) -> dict[str, Any]:
    """The US export filing block.

    An ITN outranks an exemption: it proves the EEI *was* filed, so when both
    arrive the citation wins and the exemption is not also asserted.

    This builder does not decide whether a filing was required — that is the
    carrier's and the government's answer, not this package's. It transmits
    what the operator authored.
    """

    if not itn and not exemption_legend:
        raise ValueError(
            "an EEI filing option needs either an ITN or an exemption legend"
        )

    shipper_filed: dict[str, Any] = {}
    if itn:
        shipper_filed["Code"] = EEI_PRE_DEPARTURE_ITN
        shipper_filed["PreDepartureITNNumber"] = str(itn)
    else:
        shipper_filed["Code"] = EEI_EXEMPTION
        shipper_filed["ExemptionLegend"] = str(exemption_legend)
    if shipment_reference:
        shipper_filed["EEIShipmentReferenceNumber"] = str(shipment_reference)

    return {"Code": EEI_FILED_BY_SHIPPER, "ShipperFiled": shipper_filed}


def build_invoice_form(
    *,
    products: Sequence[Mapping[str, Any]],
    currency_code: str,
    reason_for_export: str,
    invoice_number: Optional[str] = None,
    invoice_date: Optional[str] = None,
    terms_of_shipment: Optional[str] = None,
    declaration_statement: Optional[str] = None,
    eei_filing_option: Optional[Mapping[str, Any]] = None,
    sold_to: Optional[Mapping[str, Any]] = None,
    ups_generates_invoice: bool = True,
) -> dict[str, Any]:
    """The ``InternationalForms`` declaration.

    ``ups_generates_invoice`` decides whether ``FormType`` requests ``"01"``,
    and it is the whole point of this parameter.

    **``"01"`` asks UPS to GENERATE an invoice** from the ``Product`` and
    ``Contacts`` data below. ``"07"`` (see :mod:`carriers.ups.documents`)
    attaches one you already rendered. Requesting both asks for two invoices on
    one shipment — the customer's and UPS's — which is exactly what a paperless
    workflow exists to avoid, and it is a shipment-level contradiction rather
    than a cosmetic one: the commercial invoice is the document destination
    customs assesses duty against.

    So a caller lodging its own commercial invoice passes
    ``ups_generates_invoice=False``. The declaration data still rides — an EEI
    form is generated from it, and it is what UPS validates the shipment's
    customs content against — but ``"01"`` does not.

    ``FormType`` is omitted entirely when nothing is requested here, leaving
    :func:`carriers.ups.attach_paperless_documents` to set ``"07"`` alone.
    """

    if not products:
        raise ValueError("an invoice declaration needs at least one product")

    form_types: list[str] = []
    if eei_filing_option:
        form_types.append(EEI)
    if ups_generates_invoice:
        form_types.append(INVOICE)

    form: dict[str, Any] = {
        "CurrencyCode": str(currency_code).upper(),
        "ReasonForExport": str(reason_for_export),
        "Product": [dict(product) for product in products],
    }
    if invoice_number:
        form["InvoiceNumber"] = str(invoice_number)
    if invoice_date:
        form["InvoiceDate"] = str(invoice_date)
    if terms_of_shipment:
        form["TermsOfShipment"] = str(terms_of_shipment)
    if declaration_statement:
        form["DeclarationStatement"] = str(declaration_statement)
    if sold_to:
        form["Contacts"] = {"SoldTo": dict(sold_to)}
    if eei_filing_option:
        form["EEIFilingOption"] = dict(eei_filing_option)
    if form_types:
        form["FormType"] = form_types[0] if len(form_types) == 1 else form_types
    return form


def attach_international_forms(
    ship_payload: Mapping[str, Any],
    forms: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a ship payload carrying ``forms``, without mutating the input.

    Merges into any ``InternationalForms`` already present rather than
    replacing it, so this composes with
    :func:`carriers.ups.attach_paperless_documents` applied either before or
    after. The resulting ``FormType`` lists the codes in the order they were
    added — declaration-first gives ``["01","07"]``, documents-first gives
    ``["07","01"]``. UPS treats the list as a set, so both are correct.
    """

    payload = copy.deepcopy(dict(ship_payload))
    shipment_request = _ensure_dict(payload, "ShipmentRequest")
    shipment = _ensure_dict(shipment_request, "Shipment")
    service_options = _ensure_dict(shipment, "ShipmentServiceOptions")
    existing = _ensure_dict(service_options, "InternationalForms")

    # Deep, not shallow: a shallow dict() leaves the returned payload sharing
    # the caller's Product list and EEIFilingOption objects, so "does not mutate
    # its input" would hold for ship_payload and quietly fail for forms.
    incoming = copy.deepcopy(dict(forms))
    merged_types = _merge_form_types(
        existing.get("FormType"), incoming.pop("FormType", None)
    )
    existing.update(incoming)
    if merged_types is not None:
        existing["FormType"] = merged_types
    return payload


def _merge_form_types(current: Any, incoming: Any) -> Any:
    """Union of two ``FormType`` values, preserving UPS's scalar-or-list shape."""

    if current is None:
        return incoming
    if incoming is None:
        return current
    was_list = isinstance(current, list) or isinstance(incoming, list)
    ordered: list[str] = []
    for value in (current, incoming):
        for item in value if isinstance(value, list) else [value]:
            if item not in ordered:
                ordered.append(item)
    # A list in stays a list out. Collapsing ["01"] merged with "01" down to the
    # bare string "01" changed the shape a caller handed us for no reason; UPS
    # accepts either, but a builder that silently retypes its input is a trap.
    if len(ordered) == 1 and not was_list:
        return ordered[0]
    return ordered


def _ensure_dict(parent: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    value = parent.get(key)
    if value is None:
        value = {}
        parent[key] = value
    if not isinstance(value, MutableMapping):
        raise ValueError(f"{key} must be an object")
    return value


def _text(value: Any) -> str:
    """UPS wants numbers as strings, and integral floats without the ``.0``."""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _money(value: Any) -> str:
    """A currency amount as UPS wants it.

    Refuses a value that is not a number rather than stringifying it: the old
    fallback put ``"Value": "None"`` on the wire for a missing unit price, which
    is a declaration UPS cannot read and nobody can audit. Failing to CONSTRUCT
    the request is the correct local failure — judging the amount is not.
    """

    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        raise ValueError(
            f"a commodity value must be a number, got {value!r}"
        ) from None
