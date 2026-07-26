"""Retry policy shared by every carrier client.

Neither carrier SDK retried before this package existed: a 429 raised and
stopped, and ``Retry-After`` was never read. The policy lives here so adding a
status code or changing the backoff is a one-file change instead of two.
"""
from __future__ import annotations

import email.utils
import random
import time
from dataclasses import dataclass, field
from typing import Callable, FrozenSet, Mapping, Optional

# 408 and 5xx are transient by definition; 429 is the carrier asking us to
# slow down. Other 4xx mean the request itself is wrong, so retrying only
# burns quota.
DEFAULT_RETRY_STATUSES: FrozenSet[int] = frozenset({408, 429, 500, 502, 503, 504})

# Methods that can be repeated without creating a second of anything.
IDEMPOTENT_METHODS: FrozenSet[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Statuses that are safe to retry even on POST/PATCH: the carrier told us it
# did not process the request. A 5xx on ``POST /ship`` might mean the label
# was bought and the response was lost, so those are never retried
# automatically — that decision belongs to the caller, who knows whether a
# duplicate shipment is acceptable.
UNPROCESSED_STATUSES: FrozenSet[int] = frozenset({408, 429})


def retry_after_seconds(headers: Mapping[str, str]) -> Optional[float]:
    """Parse ``Retry-After``, which is either delta-seconds or an HTTP date."""

    raw = None
    for name, value in headers.items():
        if name.lower() == "retry-after":
            raw = (value or "").strip()
            break
    if not raw:
        return None

    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - time.time())


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to retry, and how long to wait between attempts."""

    attempts: int = 3
    backoff_factor: float = 0.5
    max_backoff: float = 30.0
    statuses: FrozenSet[int] = DEFAULT_RETRY_STATUSES
    respect_retry_after: bool = True
    jitter: bool = True
    # Set True only if you are prepared for a duplicate side effect: it lets
    # 5xx and connection failures retry on POST/PATCH as well.
    retry_non_idempotent: bool = False
    # Injected so tests run instantly and callers can supply their own sleep.
    sleep: Callable[[float], None] = field(default=time.sleep, compare=False)

    @classmethod
    def disabled(cls) -> "RetryPolicy":
        return cls(attempts=1)

    def should_retry(
        self,
        *,
        attempt: int,
        method: str,
        status_code: Optional[int],
    ) -> bool:
        """``attempt`` is 1-based: attempt 1 is the original request.

        ``status_code`` is ``None`` for a transport-level failure, where we
        never learned whether the carrier saw the request.
        """

        if attempt >= self.attempts:
            return False

        idempotent = self.retry_non_idempotent or method.upper() in IDEMPOTENT_METHODS
        if status_code is None:
            return idempotent
        if status_code not in self.statuses:
            return False
        return idempotent or status_code in UNPROCESSED_STATUSES

    def delay_for(self, *, attempt: int, headers: Optional[Mapping[str, str]] = None) -> float:
        """Seconds to wait before the next attempt.

        A carrier-supplied ``Retry-After`` wins over the computed backoff — it
        is the only number reflecting the carrier's actual rate-limit window.
        It is still clamped to ``max_backoff`` so a pathological header cannot
        hang the caller.
        """

        if headers and self.respect_retry_after:
            advised = retry_after_seconds(headers)
            if advised is not None:
                return min(advised, self.max_backoff)

        delay = self.backoff_factor * (2 ** (attempt - 1))
        if self.jitter:
            # Full jitter spreads a thundering herd instead of synchronising
            # every client on one backoff schedule.
            delay = random.uniform(0.0, delay)
        return min(delay, self.max_backoff)


__all__ = [
    "DEFAULT_RETRY_STATUSES",
    "IDEMPOTENT_METHODS",
    "UNPROCESSED_STATUSES",
    "RetryPolicy",
    "retry_after_seconds",
]
