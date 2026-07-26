"""UPS adapter: UPS's REST API surface over the shared carrier core.

Owns UPS's OAuth flow, versioned URL map, payload builders and error mapping —
and nothing about any other system. It never learns what an ABConnect job id
is, and it never imports another carrier.
"""
from __future__ import annotations

from .addresses import (
    CLASSIFICATION,
    VALIDATION,
    VALIDATION_AND_CLASSIFICATION,
    build_address_validation_request,
    extract_address_validation,
    extract_candidates,
    first_candidate,
)
from .client import UPSClient
from .config import CIE_BASE_URL, PRODUCTION_BASE_URL, Environment, UPSConfig
from .documents import (
    AUTHORIZATION_FORM,
    CERTIFICATE_OF_ORIGIN,
    COMMERCIAL_INVOICE,
    DECLARATION,
    EXPORT_ACCOMPANYING_DOCUMENT,
    EXPORT_LICENSE,
    IMPORT_PERMIT,
    ONE_TIME_USMCA,
    OTHER_DOCUMENT,
    PACKING_LIST,
    POWER_OF_ATTORNEY,
    SED_DOCUMENT,
    SHIPPERS_LETTER_OF_INSTRUCTION,
    USER_CREATED_FORM,
    attach_paperless_documents,
    build_push_to_repository_request,
    build_upload_request,
    build_user_created_form,
    extract_document_ids,
)
from .errors import (
    UPSAPIError,
    UPSAuthenticationError,
    UPSError,
    UPSRateLimitError,
    UPSValidationError,
)
from .forwarding import (
    build_cancel_order_request,
    build_cancel_shipment_request,
    build_label_request,
    build_manifest_request,
    forwarding_headers,
    json_patch,
    replace_op,
)
from .models import AccessToken, UPSResponse
from .oauth import authorization_url
from .pickups import (
    CANCEL_BY_ACCOUNT,
    CANCEL_BY_PRN,
    PICKUP_SERVICE_DOMESTIC,
    PICKUP_SERVICE_INTERNATIONAL,
    PICKUP_SERVICE_TRANSBORDER,
    build_pickup_rate_request,
    build_pickup_request,
    extract_pickup_confirmation,
)
from .rates import (
    SERVICE_CODES,
    build_rate_request,
    extract_rate_options,
    rate_request_from_ship_payload,
)
from .tracking import build_track_alert_subscription, extract_package_status
from .trade import (
    ACTION_SAVE,
    ACTION_VALIDATE,
    build_customs_detail_request,
    build_landed_cost_request,
    build_metadata_field,
    build_metadata_group,
    extract_landed_cost_totals,
)

__all__ = [
    "ACTION_SAVE",
    "ACTION_VALIDATE",
    "AUTHORIZATION_FORM",
    "AccessToken",
    "CANCEL_BY_ACCOUNT",
    "CANCEL_BY_PRN",
    "CERTIFICATE_OF_ORIGIN",
    "CIE_BASE_URL",
    "CLASSIFICATION",
    "COMMERCIAL_INVOICE",
    "DECLARATION",
    "EXPORT_ACCOMPANYING_DOCUMENT",
    "EXPORT_LICENSE",
    "Environment",
    "IMPORT_PERMIT",
    "ONE_TIME_USMCA",
    "OTHER_DOCUMENT",
    "PACKING_LIST",
    "PICKUP_SERVICE_DOMESTIC",
    "PICKUP_SERVICE_INTERNATIONAL",
    "PICKUP_SERVICE_TRANSBORDER",
    "POWER_OF_ATTORNEY",
    "PRODUCTION_BASE_URL",
    "SED_DOCUMENT",
    "SERVICE_CODES",
    "SHIPPERS_LETTER_OF_INSTRUCTION",
    "UPSAPIError",
    "UPSAuthenticationError",
    "UPSClient",
    "UPSConfig",
    "UPSError",
    "UPSRateLimitError",
    "UPSResponse",
    "UPSValidationError",
    "USER_CREATED_FORM",
    "VALIDATION",
    "VALIDATION_AND_CLASSIFICATION",
    "attach_paperless_documents",
    "authorization_url",
    "build_address_validation_request",
    "build_cancel_order_request",
    "build_cancel_shipment_request",
    "build_customs_detail_request",
    "build_label_request",
    "build_landed_cost_request",
    "build_manifest_request",
    "build_metadata_field",
    "build_metadata_group",
    "build_pickup_rate_request",
    "build_pickup_request",
    "build_push_to_repository_request",
    "build_rate_request",
    "build_track_alert_subscription",
    "build_upload_request",
    "build_user_created_form",
    "extract_address_validation",
    "extract_candidates",
    "extract_document_ids",
    "extract_landed_cost_totals",
    "extract_package_status",
    "extract_pickup_confirmation",
    "extract_rate_options",
    "first_candidate",
    "forwarding_headers",
    "json_patch",
    "rate_request_from_ship_payload",
    "replace_op",
]
