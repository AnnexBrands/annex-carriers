"""Shared configuration base and environment resolution.

Both carriers resolve credentials the same way — process environment first,
then an optional env file — and differ only in variable names and the
environment literals they accept. That resolution lives here once.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

PathLike = Union[str, "os.PathLike[str]"]


@dataclass(frozen=True)
class BaseConfig:
    """Fields every carrier client needs.

    Carrier configs subclass this and add their own base URLs, environment
    literals and auth extras.
    """

    client_id: str
    # Secrets carry repr=False so a logged or raised config never prints them.
    client_secret: str = field(repr=False)
    account_number: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 30.0
    user_agent: str = "annex-carriers-python"
    grant_type: str = "client_credentials"
    token_refresh_margin: int = 60

    # Retry knobs. ``retry_attempts`` counts total attempts, so 1 disables
    # retry entirely; the default retries twice after the first failure.
    retry_attempts: int = 3
    retry_backoff_factor: float = 0.5
    retry_max_backoff: float = 30.0

    @property
    def resolved_base_url(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


def env_value(
    *names: str,
    values: Optional[Dict[str, str]] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    """Return the first non-empty value across ``names``.

    The process environment wins over the env file for every name before any
    env-file value is considered, so exporting a variable always overrides a
    checked-in file.
    """

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    if values:
        for name in names:
            value = values.get(name)
            if value:
                return value
    return default


def load_env_file(env_file: PathLike) -> Dict[str, str]:
    """Parse a ``KEY=value`` env file into a dict, ignoring comments."""

    values: Dict[str, str] = {}
    for line in Path(env_file).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


__all__ = ["BaseConfig", "env_value", "load_env_file"]
