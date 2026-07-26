"""Pickup API payload builders and response parsing.

Covers the three pickup operations: availability (``POST
/pickup/v1/pickups/availabilities``), create (``POST /pickup/v1/pickups``) and
cancel (``PUT /pickup/v1/pickups/cancel``). Express (FDXE) and Ground (FDXG)
are separate pickup networks — the carrier code must match the service being
shipped.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def build_pickup_availability_request(
    pickup_address: Mapping[str, Any],
    *,
    carriers: Sequence[str] = ("FDXE",),
    dispatch_date: Optional[str] = None,
    package_ready_time: str = "09:00:00",
    customer_close_time: str = "17:00:00",
    country_relationship: str = "DOMESTIC",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pickupAddress": dict(pickup_address),
        "pickupRequestType": ["FUTURE_DAY" if dispatch_date else "SAME_DAY"],
        "carriers": list(carriers),
        "countryRelationship": country_relationship,
        "packageReadyTime": package_ready_time,
        "customerCloseTime": customer_close_time,
    }
    if dispatch_date:
        payload["dispatchDate"] = dispatch_date
    return payload


def build_pickup_request(
    account_number: str,
    *,
    pickup_contact: Mapping[str, Any],
    pickup_address: Mapping[str, Any],
    ready_timestamp: str,
    customer_close_time: str = "17:00:00",
    carrier_code: str = "FDXE",
    package_count: Optional[int] = None,
    total_weight_lb: Optional[float] = None,
    remarks: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /pickup/v1/pickups`` payload.

    ``ready_timestamp`` is FedEx's ``readyDateTimestamp`` (e.g.
    ``2026-07-06T09:00:00Z``).
    """

    origin: dict[str, Any] = {
        "pickupLocation": {
            "contact": dict(pickup_contact),
            "address": dict(pickup_address),
        },
        "readyDateTimestamp": ready_timestamp,
        "customerCloseTime": customer_close_time,
    }
    payload: dict[str, Any] = {
        "associatedAccountNumber": {"value": account_number},
        "originDetail": origin,
        "carrierCode": carrier_code,
    }
    if package_count is not None:
        payload["packageCount"] = int(package_count)
    if total_weight_lb is not None:
        payload["totalWeight"] = {"units": "LB", "value": float(total_weight_lb)}
    if remarks:
        payload["remarks"] = remarks
    return payload


def build_pickup_cancel_request(
    account_number: str,
    *,
    confirmation_code: str,
    scheduled_date: str,
    carrier_code: str = "FDXE",
    location: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "associatedAccountNumber": {"value": account_number},
        "pickupConfirmationCode": confirmation_code,
        "scheduledDate": scheduled_date,
        "carrierCode": carrier_code,
    }
    if location:
        payload["location"] = location
    return payload


def extract_pickup_confirmation(response_data: Any) -> Optional[dict[str, Any]]:
    """Return ``{confirmationCode, location, message}`` from a create response."""

    if not isinstance(response_data, Mapping):
        return None
    output = response_data.get("output") or {}
    if not isinstance(output, Mapping) or not output.get("pickupConfirmationCode"):
        return None
    return {
        "confirmationCode": output.get("pickupConfirmationCode"),
        "location": output.get("location"),
        "message": output.get("message"),
    }
