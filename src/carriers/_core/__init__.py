"""Internal infrastructure shared by the carrier adapters.

This package is deliberately underscore-prefixed: it is not a public contract
and may change without a deprecation cycle. Import from ``carriers.ups`` or
``carriers.fedex`` instead.

It knows nothing about any specific carrier — no URLs, no payload shapes, no
auth quirks. Those live in the adapters.
"""
from __future__ import annotations

from .client import BaseClient, JsonObject, bool_str
from .config import BaseConfig, env_value, load_env_file
from .errors import (
    CarrierAPIError,
    CarrierAuthenticationError,
    CarrierError,
    CarrierRateLimitError,
    CarrierTransportError,
    CarrierValidationError,
)
from .models import AccessToken, CarrierResponse
from .multipart import encode_multipart_form_data
from .resources import Resource, resource
from .retry import RetryPolicy, retry_after_seconds
from .transport import HttpResponse, Transport, UrlLibTransport, decode_response_body

__all__ = [
    "AccessToken",
    "BaseClient",
    "BaseConfig",
    "CarrierAPIError",
    "CarrierAuthenticationError",
    "CarrierError",
    "CarrierRateLimitError",
    "CarrierResponse",
    "CarrierTransportError",
    "CarrierValidationError",
    "HttpResponse",
    "JsonObject",
    "Resource",
    "RetryPolicy",
    "Transport",
    "UrlLibTransport",
    "bool_str",
    "decode_response_body",
    "encode_multipart_form_data",
    "env_value",
    "load_env_file",
    "resource",
    "retry_after_seconds",
]
