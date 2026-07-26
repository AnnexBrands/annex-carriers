"""FedEx error classes.

Each subclasses both ``FedExError`` and its carrier-agnostic counterpart, so
``except CarrierRateLimitError`` catches FedEx and UPS alike while
``except FedExRateLimitError`` still narrows to one carrier.
"""
from __future__ import annotations

from .._core.errors import (
    CarrierAPIError,
    CarrierAuthenticationError,
    CarrierError,
    CarrierRateLimitError,
    CarrierValidationError,
)


class FedExError(CarrierError):
    """Base exception for the FedEx adapter."""


class FedExAPIError(CarrierAPIError, FedExError):
    """Raised when FedEx returns a non-success HTTP response."""


class FedExAuthenticationError(CarrierAuthenticationError, FedExAPIError):
    """Raised for authentication and authorization failures."""


class FedExRateLimitError(CarrierRateLimitError, FedExAPIError):
    """Raised when FedEx rate limits the request."""


class FedExValidationError(CarrierValidationError, FedExAPIError):
    """Raised for request validation failures."""


__all__ = [
    "FedExAPIError",
    "FedExAuthenticationError",
    "FedExError",
    "FedExRateLimitError",
    "FedExValidationError",
]
