"""Rate API payload builders and response parsing.

The Ship and Rate APIs share most of the ``requestedShipment`` shape but differ
in small ways: Rate takes a single ``recipient`` where Ship takes a
``recipients`` list, and label/ETD blocks are Ship-only. To keep quoted ==
booked, ``rate_request_from_ship_payload`` derives the rate request from the
exact payload you intend to send to ``create_shipment``.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Optional, Sequence

# Ship-only payload parts the Rate API rejects or ignores.
_SHIP_ONLY_SHIPMENT_KEYS = ("labelSpecification", "shippingDocumentSpecification")


def build_rate_request(
    requested_shipment: Mapping[str, Any],
    account_number: str,
    *,
    rate_request_types: Sequence[str] = ("ACCOUNT",),
    return_transit_times: bool = True,
    carrier_codes: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /rate/v1/rates/quotes`` payload."""

    shipment = copy.deepcopy(dict(requested_shipment))
    shipment["rateRequestType"] = list(rate_request_types)
    payload: dict[str, Any] = {
        "accountNumber": {"value": account_number},
        "requestedShipment": shipment,
        "returnTransitTimes": return_transit_times,
    }
    if carrier_codes:
        payload["carrierCodes"] = list(carrier_codes)
    return payload


def rate_request_from_ship_payload(
    ship_payload: Mapping[str, Any],
    *,
    rate_request_types: Sequence[str] = ("ACCOUNT",),
    return_transit_times: bool = True,
    all_services: bool = False,
) -> dict[str, Any]:
    """Derive a rate request from a ``create_shipment`` payload.

    ``all_services=True`` drops ``serviceType`` so FedEx returns every service
    it can rate for the shipment (service shopping); the default rates exactly
    the service on the payload.
    """

    shipment = copy.deepcopy(dict(ship_payload.get("requestedShipment") or {}))
    recipients = shipment.pop("recipients", None)
    if recipients and "recipient" not in shipment:
        shipment["recipient"] = recipients[0]
    for key in _SHIP_ONLY_SHIPMENT_KEYS:
        shipment.pop(key, None)
    # ETD document references are booking artifacts; they never price a move.
    services = shipment.get("shipmentSpecialServices")
    if isinstance(services, dict):
        services.pop("etdDetail", None)
        if not services.get("specialServiceTypes") and not services:
            shipment.pop("shipmentSpecialServices", None)
    if all_services:
        shipment.pop("serviceType", None)

    account = ((ship_payload.get("accountNumber") or {}).get("value")) or ""
    return build_rate_request(
        shipment,
        account,
        rate_request_types=rate_request_types,
        return_transit_times=return_transit_times,
    )


def extract_rate_options(response_data: Any) -> list[dict[str, Any]]:
    """Flatten ``output.rateReplyDetails`` into comparable option dicts."""

    if not isinstance(response_data, Mapping):
        return []
    details = (response_data.get("output") or {}).get("rateReplyDetails") or []
    options: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, Mapping):
            continue
        rated = detail.get("ratedShipmentDetails") or [{}]
        by_type = {r.get("rateType"): r for r in rated if isinstance(r, Mapping)}
        preferred = (
            by_type.get("ACCOUNT")
            or by_type.get("RATED_ACCOUNT_SHIPMENT")
            or (rated[0] if isinstance(rated[0], Mapping) else {})
        )
        commit = detail.get("commit") or {}
        options.append(
            {
                "serviceType": detail.get("serviceType"),
                "serviceName": detail.get("serviceName"),
                "packagingType": detail.get("packagingType"),
                "totalNetCharge": preferred.get("totalNetCharge"),
                "currency": preferred.get("currency"),
                "rateType": preferred.get("rateType"),
                "transitDays": (commit.get("transitDays") or {}).get("description")
                if isinstance(commit.get("transitDays"), Mapping)
                else commit.get("transitDays"),
                "deliveryDate": commit.get("dateDetail", {}).get("dayFormat")
                if isinstance(commit.get("dateDetail"), Mapping)
                else None,
            }
        )
    return options
