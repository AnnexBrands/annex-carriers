"""Shared value objects: the OAuth token and the response envelope."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class AccessToken:
    value: str
    token_type: str
    expires_at: float
    scope: Optional[str] = None
    refresh_token: Optional[str] = None

    def is_expired(self, now: float, refresh_margin: int = 60) -> bool:
        return now >= self.expires_at - refresh_margin


@dataclass(frozen=True)
class CarrierResponse:
    """A parsed carrier response.

    ``data`` is the decoded JSON body (or the raw text when the carrier did
    not send JSON). Carrier packages subclass this only to give the type a
    recognisable name; no behaviour differs.
    """

    data: Any
    status_code: int
    headers: Mapping[str, str]
    transaction_id: Optional[str] = None

    def header(self, name: str) -> Optional[str]:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


__all__ = ["AccessToken", "CarrierResponse"]
