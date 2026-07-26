"""FedEx adapter: FedEx's REST API surface over the shared carrier core.

Owns FedEx's OAuth flow, URL map, ETD workflows and payload builders — and
nothing about any other system. It never learns what an ABConnect job id is,
and it never imports another carrier.
"""
from __future__ import annotations

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
    "build_etd_document",
    "extract_uploaded_document_id",
    "read_upload_attachment",
    "uploaded_document_reference",
]
