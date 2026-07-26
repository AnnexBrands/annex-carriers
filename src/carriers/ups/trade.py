"""International trade payload builders: landed cost, customs detail, Export Assure.

These are the four families that matter to the international lanes and that
the SDK previously did not reach. Unlike Rating and Shipping — which use UPS's
older PascalCase envelopes — the trade APIs are camelCase and un-enveloped, so
the builders here are deliberately thin: they assemble the required scaffolding
and pass commodity data through untouched.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# Customs Detail actionType values.
ACTION_VALIDATE = "validate"
ACTION_SAVE = "save"


def build_landed_cost_request(
    *,
    shipment_id: str,
    import_country_code: str,
    export_country_code: str,
    items: Sequence[Mapping[str, Any]],
    currency_code: str = "USD",
    transaction_id: Optional[str] = None,
    import_province: Optional[str] = None,
    ship_date: Optional[str] = None,
    incoterms: Optional[str] = None,
    transport_mode: Optional[str] = None,
    allow_partial_result: bool = False,
    shipment_extras: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /api/landedcost/{version}/quotes`` payload.

    ``items`` entries follow UPS's ``shipmentItems`` shape (``commodityId``,
    ``hsCode``, ``priceEach``, ``quantity``, ``UOM``, ``originCountryCode``).
    UPS requires every item to carry a ``commodityId`` unique within the
    shipment, so one is filled in positionally when absent.
    """

    if not items:
        raise ValueError("items must contain at least one commodity")

    shipment_items = []
    for index, item in enumerate(items, start=1):
        entry = dict(item)
        entry.setdefault("commodityId", str(index))
        shipment_items.append(entry)

    shipment: dict[str, Any] = {
        "id": shipment_id,
        "importCountryCode": import_country_code,
        "exportCountryCode": export_country_code,
        "shipmentItems": shipment_items,
    }
    optional = {
        "importProvince": import_province,
        "shipDate": ship_date,
        "incoterms": incoterms,
        "transportationMode": transport_mode,
    }
    shipment.update({key: value for key, value in optional.items() if value is not None})
    if shipment_extras:
        shipment.update(shipment_extras)

    payload: dict[str, Any] = {
        "currencyCode": currency_code,
        "allowPartialLandedCostResult": allow_partial_result,
        "shipment": shipment,
    }
    if transaction_id:
        payload["transID"] = transaction_id
    return payload


def extract_landed_cost_totals(response_data: Any) -> Optional[dict[str, Any]]:
    """Flatten a landed cost quote into the totals a quote screen needs."""

    if not isinstance(response_data, Mapping):
        return None
    shipment = response_data.get("shipment")
    if not isinstance(shipment, Mapping):
        return None
    return {
        "currencyCode": response_data.get("currencyCode"),
        "totalDuties": shipment.get("totalDuties"),
        "totalTaxes": shipment.get("totalTaxes"),
        "totalFees": shipment.get("totalFees"),
        "totalLandedCost": shipment.get("totalLandedCost"),
        "totalDutiesTaxesAndFees": shipment.get("totalDutiesTaxesAndFees"),
        "shipmentId": shipment.get("id"),
    }


def build_customs_detail_request(
    *,
    shipper_number: str,
    shipment_metadata: Sequence[Mapping[str, Any]],
    action_type: str = ACTION_VALIDATE,
    tracking_number: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST .../content/fields/customs-detail`` payload.

    ``action_type`` ``validate`` checks the field values without persisting
    them; ``save`` submits them against ``tracking_number``, which UPS then
    requires.
    """

    if action_type not in {ACTION_VALIDATE, ACTION_SAVE}:
        raise ValueError("action_type must be 'validate' or 'save'")
    if action_type == ACTION_SAVE and not tracking_number:
        raise ValueError("tracking_number is required when action_type is 'save'")

    payload: dict[str, Any] = {
        "actionType": action_type,
        "shipperNumber": shipper_number,
        "shipmentMetaData": [dict(group) for group in shipment_metadata],
    }
    if tracking_number:
        payload["trackingNumber"] = tracking_number
    return payload


def build_metadata_field(
    field_key: str,
    field_value: Any,
    *,
    regulation_sections: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Build one ``fields`` entry for :func:`build_customs_detail_request`."""

    field: dict[str, Any] = {"fieldKey": field_key, "fieldValue": field_value}
    if regulation_sections:
        field["regulationSections"] = [{"sectionKey": key} for key in regulation_sections]
    return field


def build_metadata_group(
    group_key: str,
    fields: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one ``shipmentMetaData`` group (e.g. ``US-IMP-CDC``)."""

    return {"groupKey": group_key, "fields": [dict(field) for field in fields]}


__all__ = [
    "ACTION_SAVE",
    "ACTION_VALIDATE",
    "build_customs_detail_request",
    "build_landed_cost_request",
    "build_metadata_field",
    "build_metadata_group",
    "extract_landed_cost_totals",
]
