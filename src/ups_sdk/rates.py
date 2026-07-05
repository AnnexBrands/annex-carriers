"""Rating API payload builders and response parsing.

The Shipping and Rating APIs share most of the ``Shipment`` shape but differ
in small ways: Rating takes ``PaymentDetails`` where Shipping takes
``PaymentInformation``, package containers are ``PackagingType`` instead of
``Packaging``, and label/forms blocks are Shipping-only. To keep quoted ==
booked, ``rate_request_from_ship_payload`` derives the rate request from the
exact payload you intend to send to ``create_shipment``.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Optional

# Common small-package service codes; Rating responses often omit
# Service.Description, so this fills in a readable name.
SERVICE_CODES = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "07": "UPS Worldwide Express",
    "08": "UPS Worldwide Expedited",
    "11": "UPS Standard",
    "12": "UPS 3 Day Select",
    "13": "UPS Next Day Air Saver",
    "14": "UPS Next Day Air Early",
    "54": "UPS Worldwide Express Plus",
    "59": "UPS 2nd Day Air A.M.",
    "65": "UPS Worldwide Saver",
    "75": "UPS Heavy Goods",
    "93": "UPS SurePost 1 lb or Greater",
}

# Shipping-only Shipment keys the Rating API rejects or ignores.
_SHIP_ONLY_SHIPMENT_KEYS = (
    "Description",
    "ReturnService",
    "ReferenceNumber",
    "MovementReferenceNumber",
    "Locale",
)


def build_rate_request(
    shipment: Mapping[str, Any],
    *,
    customer_context: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /api/rating/{version}/{requestoption}`` payload."""

    payload: dict[str, Any] = {"RateRequest": {"Shipment": copy.deepcopy(dict(shipment))}}
    if customer_context:
        payload["RateRequest"]["Request"] = {
            "TransactionReference": {"CustomerContext": customer_context}
        }
    return payload


def rate_request_from_ship_payload(
    ship_payload: Mapping[str, Any],
    *,
    all_services: bool = False,
    negotiated_rates: Optional[bool] = None,
    customer_context: Optional[str] = None,
) -> dict[str, Any]:
    """Derive a rate request from a ``create_shipment`` payload.

    ``all_services=True`` drops ``Service`` for use with the ``Shop`` request
    option so UPS returns every service it can rate (service shopping); the
    default rates exactly the service on the payload. ``negotiated_rates``
    forces ``ShipmentRatingOptions.NegotiatedRatesIndicator`` on (True) or off
    (False); ``None`` leaves the derived payload as-is.
    """

    shipment = copy.deepcopy(
        dict((ship_payload.get("ShipmentRequest") or {}).get("Shipment") or {})
    )
    payment = shipment.pop("PaymentInformation", None)
    if payment is not None and "PaymentDetails" not in shipment:
        shipment["PaymentDetails"] = payment
    for key in _SHIP_ONLY_SHIPMENT_KEYS:
        shipment.pop(key, None)

    packages = shipment.get("Package")
    if isinstance(packages, Mapping):
        packages = [packages]
    if isinstance(packages, list):
        shipment["Package"] = [_rating_package(package) for package in packages]

    # International forms are booking artifacts; they never price a move.
    services = shipment.get("ShipmentServiceOptions")
    if isinstance(services, MutableMapping):
        services.pop("InternationalForms", None)
        if not services:
            shipment.pop("ShipmentServiceOptions", None)

    if all_services:
        shipment.pop("Service", None)
    if negotiated_rates is True:
        rating_options = shipment.setdefault("ShipmentRatingOptions", {})
        rating_options["NegotiatedRatesIndicator"] = "Y"
    elif negotiated_rates is False and isinstance(
        shipment.get("ShipmentRatingOptions"), MutableMapping
    ):
        shipment["ShipmentRatingOptions"].pop("NegotiatedRatesIndicator", None)

    return build_rate_request(shipment, customer_context=customer_context)


def _rating_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a Ship ``Package`` entry to the Rating shape."""

    result = dict(package)
    packaging = result.pop("Packaging", None)
    if packaging is not None and "PackagingType" not in result:
        result["PackagingType"] = packaging
    return result


def extract_rate_options(response_data: Any) -> list[dict[str, Any]]:
    """Flatten ``RateResponse.RatedShipment`` into comparable option dicts."""

    if not isinstance(response_data, Mapping):
        return []
    rated = (response_data.get("RateResponse") or {}).get("RatedShipment") or []
    if isinstance(rated, Mapping):  # single-object responses on older versions
        rated = [rated]

    options: list[dict[str, Any]] = []
    for detail in rated:
        if not isinstance(detail, Mapping):
            continue
        service = detail.get("Service") or {}
        service_code = service.get("Code")
        total = detail.get("TotalCharges") or {}
        negotiated = (
            (detail.get("NegotiatedRateCharges") or {}).get("TotalCharge") or {}
        )
        guaranteed = detail.get("GuaranteedDelivery") or {}
        arrival = (
            ((detail.get("TimeInTransit") or {}).get("ServiceSummary") or {}).get(
                "EstimatedArrival"
            )
            or {}
        )
        options.append(
            {
                "serviceCode": service_code,
                "serviceName": service.get("Description")
                or SERVICE_CODES.get(str(service_code)),
                "totalCharges": total.get("MonetaryValue"),
                "currency": total.get("CurrencyCode"),
                "negotiatedCharges": negotiated.get("MonetaryValue"),
                "daysInTransit": guaranteed.get("BusinessDaysInTransit")
                or arrival.get("BusinessDaysInTransit"),
                "deliveryByTime": guaranteed.get("DeliveryByTime"),
                "scheduledDeliveryDate": guaranteed.get("ScheduledDeliveryDate")
                or (arrival.get("Arrival") or {}).get("Date"),
            }
        )
    return options
