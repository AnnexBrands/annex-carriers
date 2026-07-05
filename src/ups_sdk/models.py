from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class AccessToken:
    value: str
    token_type: str
    expires_at: float
    scope: Optional[str] = None

    def is_expired(self, now: float, refresh_margin: int = 60) -> bool:
        return now >= self.expires_at - refresh_margin


@dataclass(frozen=True)
class UPSResponse:
    data: Any
    status_code: int
    headers: Mapping[str, str]
    transaction_id: Optional[str] = None
