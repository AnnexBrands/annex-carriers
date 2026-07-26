from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional, Union

from .._core.config import BaseConfig, env_value, load_env_file

Environment = Literal["sandbox", "production"]

SANDBOX_BASE_URL = "https://apis-sandbox.fedex.com"
PRODUCTION_BASE_URL = "https://apis.fedex.com"
# Trade document upload lives on its own host, not the main API host.
SANDBOX_DOCUMENT_BASE_URL = "https://documentapitest.prod.fedex.com/sandbox"
PRODUCTION_DOCUMENT_BASE_URL = "https://documentapi.prod.fedex.com"


@dataclass(frozen=True)
class FedExConfig(BaseConfig):
    """Configuration for the FedEx REST API client."""

    environment: Environment = "sandbox"
    user_agent: str = "annex-carriers-fedex/0.2.0"
    document_base_url: Optional[str] = None
    child_key: Optional[str] = None
    child_secret: Optional[str] = None

    @property
    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.environment == "production":
            return PRODUCTION_BASE_URL
        return SANDBOX_BASE_URL

    @property
    def resolved_document_base_url(self) -> str:
        if self.document_base_url:
            return self.document_base_url.rstrip("/")
        if self.environment == "production":
            return PRODUCTION_DOCUMENT_BASE_URL
        return SANDBOX_DOCUMENT_BASE_URL

    @classmethod
    def from_env(
        cls,
        env_file: Optional[Union[str, "os.PathLike[str]"]] = None,
    ) -> "FedExConfig":
        """Create config from FEDEX_* environment variables."""

        values = load_env_file(env_file) if env_file else {}

        client_id = env_value("FEDEX_CLIENT_ID", "FEDEX_CLIENT", values=values)
        client_secret = env_value("FEDEX_CLIENT_SECRET", "FEDEX_SECRET", values=values)
        if not client_id or not client_secret:
            raise ValueError(
                "FEDEX_CLIENT_ID/FEDEX_CLIENT and FEDEX_CLIENT_SECRET/FEDEX_SECRET "
                "are required to build FedExConfig."
            )

        environment = (
            env_value("FEDEX_ENVIRONMENT", values=values, default="sandbox") or "sandbox"
        ).lower()
        if environment in {"test", "cie"}:
            environment = "sandbox"
        if environment not in {"sandbox", "production"}:
            raise ValueError("FEDEX_ENVIRONMENT must be 'sandbox' or 'production'.")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            account_number=env_value("FEDEX_ACCOUNT_NUMBER", "FEDEX_ACCOUNT", values=values),
            environment=environment,  # type: ignore[arg-type]
            base_url=env_value("FEDEX_BASE_URL", values=values),
            document_base_url=env_value("FEDEX_DOCUMENT_BASE_URL", values=values),
            grant_type=env_value(
                "FEDEX_GRANT_TYPE", values=values, default="client_credentials"
            )
            or "client_credentials",
            child_key=env_value("FEDEX_CHILD_KEY", values=values),
            child_secret=env_value("FEDEX_CHILD_SECRET", values=values),
        )


__all__ = [
    "Environment",
    "FedExConfig",
    "PRODUCTION_BASE_URL",
    "PRODUCTION_DOCUMENT_BASE_URL",
    "SANDBOX_BASE_URL",
    "SANDBOX_DOCUMENT_BASE_URL",
]
