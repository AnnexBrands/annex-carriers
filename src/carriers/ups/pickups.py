"""Pickup API payload builders and response parsing.

Covers the on-demand pickup operations: rate (``POST
/api/shipments/{version}/pickup/{pickuptype}``), create (``POST
/api/pickupcreation/{version}/pickup``) and cancel (``DELETE
/api/shipments/{version}/pickup/{CancelBy}`` with the PRN in a header).

Pickup addresses use the Pickup API's own field names — ``AddressLine`` is a
single string and the state field is ``StateProvince`` — not the Ship API's
``Address`` shape.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

CANCEL_BY_ACCOUNT = "01"
CANCEL_BY_PRN = "02"

# PickupPiece service codes (the pickup network being dispatched).
PICKUP_SERVICE_DOMESTIC = "001"
PICKUP_SERVICE_INTERNATIONAL = "002"
PICKUP_SERVICE_TRANSBORDER = "003"


def build_pickup_rate_request(
    pickup_address: Mapping[str, Any],
    *,
    pickup_date: str,
    ready_time: str,
    close_time: str,
    alternate_address_indicator: str = "N",
    service_date_option: str = "02",
) -> dict[str, Any]:
    """Assemble a ``PickupRateRequest`` payload.

    ``pickup_date`` is ``YYYYMMDD``; times are 24-hour ``HHMM``.
    """

    return {
        "PickupRateRequest": {
            "PickupAddress": dict(pickup_address),
            "AlternateAddressIndicator": alternate_address_indicator,
            "ServiceDateOption": service_date_option,
            "PickupDateInfo": {
                "PickupDate": pickup_date,
                "ReadyTime": ready_time,
                "CloseTime": close_time,
            },
        }
    }


def build_pickup_request(
    account_number: str,
    *,
    pickup_address: Mapping[str, Any],
    pickup_date: str,
    ready_time: str,
    close_time: str,
    pieces: Sequence[Mapping[str, Any]],
    account_country_code: str = "US",
    rate_pickup: bool = False,
    alternate_address_indicator: str = "N",
    total_weight_lb: Optional[float] = None,
    overweight: bool = False,
    payment_method: str = "01",
    special_instruction: Optional[str] = None,
    reference_number: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /api/pickupcreation/{version}/pickup`` payload.

    ``pieces`` entries follow UPS's ``PickupPiece`` shape (``ServiceCode``,
    ``Quantity``, ``DestinationCountryCode``, ``ContainerCode``).
    ``payment_method`` ``01`` bills the pickup to the shipper account.
    """

    payload: dict[str, Any] = {
        "PickupCreationRequest": {
            "RatePickupIndicator": "Y" if rate_pickup else "N",
            "Shipper": {
                "Account": {
                    "AccountNumber": account_number,
                    "AccountCountryCode": account_country_code,
                }
            },
            "PickupDateInfo": {
                "PickupDate": pickup_date,
                "ReadyTime": ready_time,
                "CloseTime": close_time,
            },
            "PickupAddress": dict(pickup_address),
            "AlternateAddressIndicator": alternate_address_indicator,
            "PickupPiece": [dict(piece) for piece in pieces],
            "OverweightIndicator": "Y" if overweight else "N",
            "PaymentMethod": payment_method,
        }
    }
    request = payload["PickupCreationRequest"]
    if total_weight_lb is not None:
        request["TotalWeight"] = {
            "Weight": str(total_weight_lb),
            "UnitOfMeasurement": "LBS",
        }
    if special_instruction:
        request["SpecialInstruction"] = special_instruction
    if reference_number:
        request["ReferenceNumber"] = reference_number
    return payload


def extract_pickup_confirmation(response_data: Any) -> Optional[dict[str, Any]]:
    """Return ``{prn, rateStatus, grandTotal, currency}`` from a create response."""

    if not isinstance(response_data, Mapping):
        return None
    output = response_data.get("PickupCreationResponse")
    if not isinstance(output, Mapping) or not output.get("PRN"):
        return None
    rate_result = output.get("RateResult") or {}
    return {
        "prn": output.get("PRN"),
        "rateStatus": (output.get("RateStatus") or {}).get("Description"),
        "grandTotal": rate_result.get("GrandTotalOfAllCharge"),
        "currency": rate_result.get("CurrencyCode"),
    }
