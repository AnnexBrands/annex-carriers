"""OAuth helpers for the authorization-code grant.

The client-credentials grant is what server-to-server integrations use and is
handled entirely inside ``UPSClient``. The authorization-code grant exists for
flows where a UPS account holder grants your app access interactively; it needs
a browser redirect, so the URL building and the code exchange are separate
steps that no client can perform on its own.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlencode

from . import endpoints
from .config import UPSConfig


def authorization_url(
    config: UPSConfig,
    *,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
    scope: Optional[Sequence[str]] = None,
) -> str:
    """Build the URL to send a UPS account holder to.

    They sign in at UPS and are redirected back to ``redirect_uri`` with a
    ``code`` query parameter; feed that to ``UPSClient.exchange_authorization_code``.
    ``state`` should be an unguessable value you store and compare on return —
    it is the CSRF defence for the redirect.
    """

    target = redirect_uri or config.redirect_uri
    if not target:
        raise ValueError("redirect_uri is required (or set it on UPSConfig).")

    query: dict[str, Any] = {
        "client_id": config.client_id,
        "redirect_uri": target,
        "response_type": "code",
    }
    if state:
        query["state"] = state
    if scope:
        query["scope"] = " ".join(scope)
    return f"{config.resolved_base_url}{endpoints.OAUTH_AUTHORIZE}?{urlencode(query)}"


def parse_token_response(payload: Any) -> Mapping[str, Any]:
    """Validate that an OAuth response actually carries a token."""

    if not isinstance(payload, Mapping) or "access_token" not in payload:
        raise ValueError("UPS OAuth response did not include an access token.")
    return payload


__all__ = ["authorization_url", "parse_token_response"]
