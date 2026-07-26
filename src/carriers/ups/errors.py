"""UPS error classes.

Each subclasses both ``UPSError`` and its carrier-agnostic counterpart, so
``except CarrierRateLimitError`` catches UPS and FedEx alike while
``except UPSRateLimitError`` still narrows to one carrier.
"""
from __future__ import annotations

from .._core.errors import (
    CarrierAPIError,
    CarrierAuthenticationError,
    CarrierError,
    CarrierRateLimitError,
    CarrierValidationError,
)


class UPSError(CarrierError):
    """Base exception for the UPS adapter."""


class UPSAPIError(CarrierAPIError, UPSError):
    """Raised when UPS returns a non-success HTTP response."""


class UPSAuthenticationError(CarrierAuthenticationError, UPSAPIError):
    """Raised for authentication and authorization failures."""


class UPSRateLimitError(CarrierRateLimitError, UPSAPIError):
    """Raised when UPS rate limits the request."""


class UPSValidationError(CarrierValidationError, UPSAPIError):
    """Raised for request validation failures."""


__all__ = [
    "UPSAPIError",
    "UPSAuthenticationError",
    "UPSError",
    "UPSRateLimitError",
    "UPSValidationError",
]
