"""Address Validation API payload builders and response parsing.

``POST /address/v1/addresses/resolve`` normalizes, classifies (BUSINESS /
RESIDENTIAL / MIXED), and DPV-checks addresses before a label is bought —
catching bad recipient addresses pre-booking instead of as a carrier
correction surcharge after delivery.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def build_address_validation_request(
    addresses: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assemble a resolve payload from plain address dicts.

    Each address uses Ship-payload field names (``streetLines``, ``city``,
    ``stateOrProvinceCode``, ``postalCode``, ``countryCode``).
    """

    if not addresses:
        raise ValueError("addresses must contain at least one address")
    return {
        "addressesToValidate": [{"address": dict(address)} for address in addresses]
    }


def extract_resolved_addresses(response_data: Any) -> list[dict[str, Any]]:
    """Flatten ``output.resolvedAddresses`` into decision-ready dicts.

    ``matched`` distills FedEx's attribute soup: DPV (US) or an exact/
    standardized match means the address is deliverable as given.
    """

    if not isinstance(response_data, Mapping):
        return []
    resolved = (response_data.get("output") or {}).get("resolvedAddresses") or []
    results: list[dict[str, Any]] = []
    for entry in resolved:
        if not isinstance(entry, Mapping):
            continue
        attributes = entry.get("attributes") or {}
        if isinstance(attributes, list):  # some responses use [{name, value}]
            attributes = {
                a.get("name"): a.get("value") for a in attributes if isinstance(a, Mapping)
            }
        matched = str(attributes.get("DPV", attributes.get("Matched", ""))).lower() == "true"
        results.append(
            {
                "classification": entry.get("classification"),
                "matched": matched,
                "streetLines": entry.get("streetLinesToken") or [],
                "city": (entry.get("cityToken") or [{}])[0].get("value")
                if entry.get("cityToken")
                else entry.get("city"),
                "stateOrProvinceCode": entry.get("stateOrProvinceCode"),
                "postalCode": (entry.get("parsedPostalCode") or {}).get("base")
                or entry.get("postalCode"),
                "countryCode": entry.get("countryCode"),
                "attributes": attributes,
                "customerMessages": entry.get("customerMessages") or [],
            }
        )
    return results


def first_resolved_address(response_data: Any) -> Optional[dict[str, Any]]:
    resolved = extract_resolved_addresses(response_data)
    return resolved[0] if resolved else None
