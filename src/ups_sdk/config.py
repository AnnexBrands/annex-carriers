from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union

Environment = Literal["cie", "production"]

# UPS calls its test environment the Customer Integration Environment (CIE).
CIE_BASE_URL = "https://wwwcie.ups.com"
PRODUCTION_BASE_URL = "https://onlinetools.ups.com"


@dataclass(frozen=True)
class UPSConfig:
    """Configuration for the UPS REST API client."""

    client_id: str
    client_secret: str
    account_number: Optional[str] = None
    environment: Environment = "cie"
    base_url: Optional[str] = None
    timeout: float = 30.0
    user_agent: str = "ups-api-sdk-python/0.1.0"
    grant_type: str = "client_credentials"
    transaction_src: str = "testing"
    token_refresh_margin: int = 60

    @property
    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.environment == "production":
            return PRODUCTION_BASE_URL
        return CIE_BASE_URL

    @classmethod
    def from_env(cls, env_file: Optional[Union[str, os.PathLike[str]]] = None) -> "UPSConfig":
        """Create config from UPS_* environment variables."""

        values = _load_env_file(env_file) if env_file else {}

        client_id = _env("UPS_CLIENT_ID", "UPS_CLIENT", values=values)
        client_secret = _env("UPS_CLIENT_SECRET", "UPS_SECRET", values=values)
        if not client_id or not client_secret:
            raise ValueError(
                "UPS_CLIENT_ID/UPS_CLIENT and UPS_CLIENT_SECRET/UPS_SECRET "
                "are required to build UPSConfig."
            )

        environment = _env("UPS_ENVIRONMENT", values=values, default="cie").lower()
        if environment in {"test", "sandbox"}:
            environment = "cie"
        if environment not in {"cie", "production"}:
            raise ValueError("UPS_ENVIRONMENT must be 'cie' (test) or 'production'.")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            account_number=_env(
                "UPS_ACCOUNT_NUMBER", "UPS_ACCOUNT", "UPS_SHIPPER_NUMBER", values=values
            ),
            environment=environment,  # type: ignore[arg-type]
            base_url=_env("UPS_BASE_URL", values=values),
            grant_type=_env("UPS_GRANT_TYPE", values=values, default="client_credentials"),
            transaction_src=_env("UPS_TRANSACTION_SRC", values=values, default="testing"),
        )


def _env(*names: str, values: dict[str, str], default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    for name in names:
        value = values.get(name)
        if value:
            return value
    return default


def _load_env_file(env_file: Union[str, os.PathLike[str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(env_file).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
