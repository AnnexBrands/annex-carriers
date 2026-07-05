"""Address Validation (XAV) API payload builders and response parsing.

``POST /api/addressvalidation/{version}/{requestoption}`` street-level
validates and classifies (COMMERCIAL / RESIDENTIAL) US and Puerto Rico
addresses before a label is bought — catching bad recipient addresses
pre-booking instead of as a carrier correction surcharge after delivery.
In the CIE test environment only NY and CA addresses produce results.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

# requestoption path values
VALIDATION = 1
CLASSIFICATION = 2
VALIDATION_AND_CLASSIFICATION = 3

_ADDRESS_KEY_FORMAT_KEYS = {
    "PoliticalDivision1",
    "PoliticalDivision2",
    "PostcodePrimaryLow",
    "PostcodeExtendedLow",
    "Region",
    "Urbanization",
    "ConsigneeName",
    "AttentionName",
    "BuildingName",
}


def build_address_validation_request(
    address: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble an XAV payload from a plain address dict.

    Accepts either UPS ``AddressKeyFormat`` field names directly, or the
    Ship-payload ``Address`` names (``AddressLine``, ``City``,
    ``StateProvinceCode``, ``PostalCode``, ``CountryCode``), which are
    translated to their AddressKeyFormat equivalents.
    """

    if not address:
        raise ValueError("address must not be empty")
    if _ADDRESS_KEY_FORMAT_KEYS & set(address):
        key_format = dict(address)
    else:
        key_format = {
            key: value
            for key, value in address.items()
            if key not in {"City", "StateProvinceCode", "PostalCode"}
        }
        if address.get("City"):
            key_format["PoliticalDivision2"] = address["City"]
        if address.get("StateProvinceCode"):
            key_format["PoliticalDivision1"] = address["StateProvinceCode"]
        postal = str(address.get("PostalCode") or "")
        if postal:
            primary, _, extended = postal.partition("-")
            key_format["PostcodePrimaryLow"] = primary
            if extended:
                key_format["PostcodeExtendedLow"] = extended
    lines = key_format.get("AddressLine")
    if isinstance(lines, str):
        key_format["AddressLine"] = [lines]
    return {"XAVRequest": {"AddressKeyFormat": key_format}}


def extract_address_validation(response_data: Any) -> Optional[dict[str, Any]]:
    """Flatten an ``XAVResponse`` into a decision-ready dict.

    ``valid`` reflects UPS's ``ValidAddressIndicator``: the address matched a
    deliverable street-level record as given. Ambiguous responses carry the
    suggested corrections in ``candidates``.
    """

    if not isinstance(response_data, Mapping):
        return None
    xav = response_data.get("XAVResponse")
    if not isinstance(xav, Mapping):
        return None
    classification = xav.get("AddressClassification") or {}
    return {
        "valid": "ValidAddressIndicator" in xav,
        "ambiguous": "AmbiguousAddressIndicator" in xav,
        "noCandidates": "NoCandidatesIndicator" in xav,
        "classification": classification.get("Description"),
        "classificationCode": classification.get("Code"),
        "candidates": extract_candidates(response_data),
    }


def extract_candidates(response_data: Any) -> list[dict[str, Any]]:
    """Flatten ``XAVResponse.Candidate`` entries into plain address dicts."""

    if not isinstance(response_data, Mapping):
        return []
    candidates: Union[Mapping[str, Any], Sequence[Any], None] = (
        response_data.get("XAVResponse") or {}
    ).get("Candidate")
    if candidates is None:
        return []
    if isinstance(candidates, Mapping):  # single candidate arrives as an object
        candidates = [candidates]

    results: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, Mapping):
            continue
        key_format = entry.get("AddressKeyFormat") or {}
        lines = key_format.get("AddressLine") or []
        if isinstance(lines, str):
            lines = [lines]
        classification = entry.get("AddressClassification") or {}
        results.append(
            {
                "classification": classification.get("Description"),
                "addressLines": list(lines),
                "city": key_format.get("PoliticalDivision2"),
                "stateOrProvince": key_format.get("PoliticalDivision1"),
                "postalCode": key_format.get("PostcodePrimaryLow"),
                "postalCodeExtended": key_format.get("PostcodeExtendedLow"),
                "countryCode": key_format.get("CountryCode"),
            }
        )
    return results


def first_candidate(response_data: Any) -> Optional[dict[str, Any]]:
    candidates = extract_candidates(response_data)
    return candidates[0] if candidates else None
