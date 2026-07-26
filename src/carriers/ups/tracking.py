"""Tracking helpers: response flattening and Track Alert subscriptions.

Track Alert registers a webhook destination against a list of tracking
numbers; UPS then POSTs scan events to it. The ``standard`` and ``enhanced``
subscription endpoints take the same body and differ only in the event detail
they deliver.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# Credential types UPS accepts on the webhook destination.
CREDENTIAL_BEARER = "Bearer"
CREDENTIAL_BASIC = "Basic"


def build_track_alert_subscription(
    tracking_numbers: Sequence[str],
    *,
    destination_url: str,
    credential: str,
    credential_type: str = CREDENTIAL_BEARER,
    country_code: str = "US",
    locale: str = "en_US",
    scan_preference: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Assemble a Track Alert subscription payload.

    ``credential`` is what UPS will present back to ``destination_url`` on
    each callback — it is how your endpoint authenticates UPS, so it must be a
    secret your receiver checks rather than a placeholder.
    """

    if not tracking_numbers:
        raise ValueError("tracking_numbers must contain at least one number")
    if not destination_url:
        raise ValueError("destination_url is required")

    payload: dict[str, Any] = {
        "locale": locale,
        "countryCode": country_code,
        "trackingNumberList": list(tracking_numbers),
        "destination": {
            "url": destination_url,
            "credentialType": credential_type,
            "credential": credential,
        },
    }
    if scan_preference:
        payload["scanPreference"] = list(scan_preference)
    return payload


def extract_package_status(response_data: Any) -> Optional[dict[str, Any]]:
    """Flatten a ``trackResponse`` into the fields a status screen needs.

    Returns the first package of the first shipment — the common case for a
    single-inquiry track. Multi-package shipments should read
    ``trackResponse.shipment`` directly.
    """

    if not isinstance(response_data, Mapping):
        return None
    shipments = (response_data.get("trackResponse") or {}).get("shipment") or []
    if isinstance(shipments, Mapping):
        shipments = [shipments]
    for shipment in shipments:
        if not isinstance(shipment, Mapping):
            continue
        packages = shipment.get("package") or []
        if isinstance(packages, Mapping):
            packages = [packages]
        for package in packages:
            if not isinstance(package, Mapping):
                continue
            activities = package.get("activity") or []
            if isinstance(activities, Mapping):
                activities = [activities]
            latest = activities[0] if activities else {}
            status = (latest or {}).get("status") or {}
            delivery_date = _first_date(package.get("deliveryDate"))
            return {
                "inquiryNumber": shipment.get("inquiryNumber"),
                "trackingNumber": package.get("trackingNumber"),
                "statusCode": status.get("code"),
                "statusType": status.get("type"),
                "statusDescription": status.get("description"),
                "lastActivityDate": (latest or {}).get("date"),
                "lastActivityTime": (latest or {}).get("time"),
                "deliveryDate": delivery_date,
                "service": (package.get("service") or {}).get("description"),
            }
    return None


def _first_date(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        return value.get("date")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for entry in value:
            if isinstance(entry, Mapping) and entry.get("date"):
                return entry["date"]
    return None


__all__ = [
    "CREDENTIAL_BASIC",
    "CREDENTIAL_BEARER",
    "build_track_alert_subscription",
    "extract_package_status",
]
