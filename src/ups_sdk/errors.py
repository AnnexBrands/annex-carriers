from __future__ import annotations

from typing import Any, Mapping, Optional


class UPSError(Exception):
    """Base exception for this package."""


class UPSAPIError(UPSError):
    """Raised when UPS returns a non-success HTTP response."""

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


class UPSAuthenticationError(UPSAPIError):
    """Raised for authentication and authorization failures."""


class UPSRateLimitError(UPSAPIError):
    """Raised when UPS rate limits the request."""


class UPSValidationError(UPSAPIError):
    """Raised for request validation failures."""
