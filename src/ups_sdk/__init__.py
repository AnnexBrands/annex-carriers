"""Python SDK for UPS REST APIs."""

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
from .config import Environment, UPSConfig
from .documents import (
    COMMERCIAL_INVOICE,
    DECLARATION,
    PACKING_LIST,
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
from .models import AccessToken, UPSResponse
from .pickups import (
    CANCEL_BY_ACCOUNT,
    CANCEL_BY_PRN,
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

__all__ = [
    "AccessToken",
    "CANCEL_BY_ACCOUNT",
    "CANCEL_BY_PRN",
    "CLASSIFICATION",
    "COMMERCIAL_INVOICE",
    "DECLARATION",
    "Environment",
    "PACKING_LIST",
    "SERVICE_CODES",
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
    "build_address_validation_request",
    "build_pickup_rate_request",
    "build_pickup_request",
    "build_push_to_repository_request",
    "build_rate_request",
    "build_upload_request",
    "build_user_created_form",
    "extract_address_validation",
    "extract_candidates",
    "extract_document_ids",
    "extract_pickup_confirmation",
    "extract_rate_options",
    "first_candidate",
    "rate_request_from_ship_payload",
]

__version__ = "0.1.0"
