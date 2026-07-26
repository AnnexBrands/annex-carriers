"""FedEx adapter: FedEx's REST API surface over the shared carrier core.

Owns FedEx's OAuth flow, URL map, ETD workflows and payload builders — and
nothing about any other system. It never learns what an ABConnect job id is,
and it never imports another carrier.
"""
from __future__ import annotations

from .addresses import (
    build_address_validation_request,
    extract_resolved_addresses,
    first_resolved_address,
)
from .client import FedExClient
from .config import (
    PRODUCTION_BASE_URL,
    PRODUCTION_DOCUMENT_BASE_URL,
    SANDBOX_BASE_URL,
    SANDBOX_DOCUMENT_BASE_URL,
    Environment,
    FedExConfig,
)
from .documents import (
    COMMERCIAL_INVOICE,
    ELECTRONIC_TRADE_DOCUMENTS,
    POSTSHIPMENT_WORKFLOW,
    PRESHIPMENT_WORKFLOW,
    UploadAttachment,
    attach_pre_shipment_documents,
    build_etd_document,
    extract_uploaded_document_id,
    read_upload_attachment,
    uploaded_document_reference,
)
from .errors import (
    FedExAPIError,
    FedExAuthenticationError,
    FedExError,
    FedExRateLimitError,
    FedExValidationError,
)
from .models import AccessToken, FedExResponse
from .pickups import (
    build_pickup_availability_request,
    build_pickup_cancel_request,
    build_pickup_request,
    extract_pickup_confirmation,
)
from .rates import (
    build_rate_request,
    extract_rate_options,
    rate_request_from_ship_payload,
)

__all__ = [
    "AccessToken",
    "COMMERCIAL_INVOICE",
    "ELECTRONIC_TRADE_DOCUMENTS",
    "Environment",
    "FedExAPIError",
    "FedExAuthenticationError",
    "FedExClient",
    "FedExConfig",
    "FedExError",
    "FedExRateLimitError",
    "FedExResponse",
    "FedExValidationError",
    "POSTSHIPMENT_WORKFLOW",
    "PRESHIPMENT_WORKFLOW",
    "PRODUCTION_BASE_URL",
    "PRODUCTION_DOCUMENT_BASE_URL",
    "SANDBOX_BASE_URL",
    "SANDBOX_DOCUMENT_BASE_URL",
    "UploadAttachment",
    "attach_pre_shipment_documents",
    "build_address_validation_request",
    "build_etd_document",
    "build_pickup_availability_request",
    "build_pickup_cancel_request",
    "build_pickup_request",
    "build_rate_request",
    "extract_pickup_confirmation",
    "extract_rate_options",
    "extract_resolved_addresses",
    "extract_uploaded_document_id",
    "first_resolved_address",
    "rate_request_from_ship_payload",
    "read_upload_attachment",
    "uploaded_document_reference",
]
