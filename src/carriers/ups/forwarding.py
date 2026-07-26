"""UPS Forwarding (freight forwarding) constants and helpers.

Forwarding is the odd family out: it is camelCase, it authenticates with two
extra headers (``X-BusinessGUID`` and ``X-ClientId``) that no other UPS API
uses, several of its mutations are JSON-Patch documents, and UPS's own path
spells the word "fowarding". All four quirks are reproduced faithfully here
rather than corrected, because the server expects them.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# Order/quote search request types.
REQUEST_TYPE_AIR = "Air"
REQUEST_TYPE_OCEAN = "Ocean"
REQUEST_TYPE_GROUND = "Ground"

# Document formats accepted by the label and manifest endpoints.
FORMAT_PDF = "PDF"
FORMAT_ZPL = "ZPL"
FORMAT_DATA = "DATA"


def forwarding_headers(
    *,
    business_guid: Optional[str] = None,
    client_id: Optional[str] = None,
) -> dict[str, str]:
    """Build the two Forwarding-only headers, omitting unset ones."""

    headers: dict[str, str] = {}
    if business_guid:
        headers["X-BusinessGUID"] = business_guid
    if client_id:
        headers["X-ClientId"] = client_id
    return headers


def build_cancel_order_request(
    *,
    account: str,
    order_number: str,
    language: str = "en-US",
) -> dict[str, Any]:
    """Body for ``DELETE /api/fowarding/{version}/orders``."""

    return {"account": account, "orderNumber": order_number, "language": language}


def build_cancel_shipment_request(
    *,
    shipper_account_number: str,
    shipment_number: str,
    language: str = "en-US",
) -> dict[str, Any]:
    """Body for ``DELETE /api/fowarding/{version}/shipments``."""

    return {
        "shipperAccountNumber": shipper_account_number,
        "shipmentNumber": shipment_number,
        "language": language,
    }


def build_label_request(
    *,
    shipper_account_number: str,
    order_number: str,
    document_format: str = FORMAT_PDF,
    layout: Optional[str] = None,
) -> dict[str, Any]:
    """Body for the label re-print endpoint."""

    payload: dict[str, Any] = {
        "shipperAccountNumber": shipper_account_number,
        "orderNumber": order_number,
        "format": document_format,
    }
    if layout:
        payload["layout"] = layout
    return payload


def build_manifest_request(
    *,
    account_number: str,
    manifest_number: str,
    manifest_format: str = FORMAT_DATA,
    language: str = "en-US",
) -> dict[str, Any]:
    """Body for the manifest creation endpoint."""

    return {
        "accountNumber": account_number,
        "manifestNumber": manifest_number,
        "manifestFormat": manifest_format,
        "language": language,
    }


def json_patch(operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalise a JSON-Patch document for the PATCH endpoints."""

    if not operations:
        raise ValueError("operations must contain at least one patch entry")
    return [dict(operation) for operation in operations]


def replace_op(path: str, value: Any) -> dict[str, Any]:
    """One ``{"op": "replace", ...}`` entry, the only op Forwarding accepts."""

    return {"op": "replace", "path": path, "value": value}


__all__ = [
    "FORMAT_DATA",
    "FORMAT_PDF",
    "FORMAT_ZPL",
    "REQUEST_TYPE_AIR",
    "REQUEST_TYPE_GROUND",
    "REQUEST_TYPE_OCEAN",
    "build_cancel_order_request",
    "build_cancel_shipment_request",
    "build_label_request",
    "build_manifest_request",
    "forwarding_headers",
    "json_patch",
    "replace_op",
]
