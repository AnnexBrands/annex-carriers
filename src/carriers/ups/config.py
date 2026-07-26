from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional, Union

from .._core.config import BaseConfig, env_value, load_env_file

Environment = Literal["cie", "production"]

# UPS calls its test environment the Customer Integration Environment (CIE).
CIE_BASE_URL = "https://wwwcie.ups.com"
PRODUCTION_BASE_URL = "https://onlinetools.ups.com"


@dataclass(frozen=True)
class UPSConfig(BaseConfig):
    """Configuration for the UPS REST API client."""

    environment: Environment = "cie"
    user_agent: str = "annex-carriers-ups/0.2.0"
    transaction_src: str = "testing"
    #: Only needed for the authorization-code grant; the client-credentials
    #: flow this SDK defaults to never uses it.
    redirect_uri: Optional[str] = None

    @property
    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.environment == "production":
            return PRODUCTION_BASE_URL
        return CIE_BASE_URL

    @classmethod
    def from_env(
        cls,
        env_file: Optional[Union[str, "os.PathLike[str]"]] = None,
    ) -> "UPSConfig":
        """Create config from UPS_* environment variables."""

        values = load_env_file(env_file) if env_file else {}

        client_id = env_value("UPS_CLIENT_ID", "UPS_CLIENT", values=values)
        client_secret = env_value("UPS_CLIENT_SECRET", "UPS_SECRET", values=values)
        if not client_id or not client_secret:
            raise ValueError(
                "UPS_CLIENT_ID/UPS_CLIENT and UPS_CLIENT_SECRET/UPS_SECRET "
                "are required to build UPSConfig."
            )

        environment = (
            env_value("UPS_ENVIRONMENT", values=values, default="cie") or "cie"
        ).lower()
        if environment in {"test", "sandbox"}:
            environment = "cie"
        if environment not in {"cie", "production"}:
            raise ValueError("UPS_ENVIRONMENT must be 'cie' (test) or 'production'.")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            account_number=env_value(
                "UPS_ACCOUNT_NUMBER", "UPS_ACCOUNT", "UPS_SHIPPER_NUMBER", values=values
            ),
            environment=environment,  # type: ignore[arg-type]
            base_url=env_value("UPS_BASE_URL", values=values),
            grant_type=env_value(
                "UPS_GRANT_TYPE", values=values, default="client_credentials"
            )
            or "client_credentials",
            transaction_src=env_value("UPS_TRANSACTION_SRC", values=values, default="testing")
            or "testing",
            redirect_uri=env_value("UPS_REDIRECT_URI", values=values),
        )


__all__ = ["CIE_BASE_URL", "PRODUCTION_BASE_URL", "Environment", "UPSConfig"]
