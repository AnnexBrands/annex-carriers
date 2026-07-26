"""Carrier-agnostic error taxonomy.

Each carrier package subclasses these so callers can catch either the shared
base (``CarrierAPIError``) or the carrier-specific class. The status-to-class
mapping lives once, in :class:`carriers._core.client.BaseClient`.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


class CarrierError(Exception):
    """Base exception for every carrier package in this distribution."""


class CarrierAPIError(CarrierError):
    """Raised when a carrier returns a non-success HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        transaction_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response = response
        self.headers = headers or {}
        self.transaction_id = transaction_id


class CarrierAuthenticationError(CarrierAPIError):
    """Raised for authentication and authorization failures."""


class CarrierRateLimitError(CarrierAPIError):
    """Raised when a carrier rate limits the request.

    ``retry_after`` carries the parsed ``Retry-After`` header in seconds when
    the carrier sent one, so callers that disable automatic retry can still
    back off correctly.
    """

    @property
    def retry_after(self) -> Optional[float]:
        from .retry import retry_after_seconds

        return retry_after_seconds(self.headers)


class CarrierValidationError(CarrierAPIError):
    """Raised for request validation failures."""


class CarrierTransportError(CarrierError):
    """Raised when the request never produced an HTTP response.

    Connection resets, DNS failures and timeouts surface here rather than as a
    raw ``URLError``, so callers can distinguish "the carrier said no" from
    "we never reached the carrier".
    """

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


__all__ = [
    "CarrierAPIError",
    "CarrierAuthenticationError",
    "CarrierError",
    "CarrierRateLimitError",
    "CarrierTransportError",
    "CarrierValidationError",
]
