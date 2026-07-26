"""The shared client: transport, token lifecycle, retry, error mapping, logging.

Everything here is carrier-agnostic. A carrier package subclasses
:class:`BaseClient`, sets a handful of class attributes and implements
``_fetch_token``; its own module then contains only URLs, payload builders and
auth quirks.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from threading import RLock
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple, Type

from .config import BaseConfig
from .errors import (
    CarrierAPIError,
    CarrierAuthenticationError,
    CarrierRateLimitError,
    CarrierTransportError,
    CarrierValidationError,
)
from .models import AccessToken, CarrierResponse
from .retry import RetryPolicy
from .transport import HttpResponse, Transport, UrlLibTransport
from urllib.parse import urlencode

JsonObject = Mapping[str, Any]


class BaseClient:
    """Synchronous HTTP client shared by every carrier adapter."""

    # --- carrier hooks -------------------------------------------------
    #: Lowercase slug used for the logger name.
    carrier_name: str = "carrier"
    #: How the carrier writes its own name, for error messages.
    carrier_label: str = "Carrier"
    api_error_class: Type[CarrierAPIError] = CarrierAPIError
    authentication_error_class: Type[CarrierAPIError] = CarrierAuthenticationError
    rate_limit_error_class: Type[CarrierAPIError] = CarrierRateLimitError
    validation_error_class: Type[CarrierAPIError] = CarrierValidationError
    response_class: Type[CarrierResponse] = CarrierResponse

    #: Response headers, in priority order, that carry the carrier's own
    #: transaction id.
    transaction_id_headers: Tuple[str, ...] = ()
    #: Envelope keys to descend through before looking for ``errors``. UPS
    #: nests them under ``response``; FedEx puts them at the top level.
    error_envelope_keys: Tuple[str, ...] = ()

    def __init__(
        self,
        config: BaseConfig,
        *,
        transport: Optional[Transport] = None,
        retry_policy: Optional[RetryPolicy] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self._transport = transport or UrlLibTransport()
        self._token: Optional[AccessToken] = None
        self._lock = RLock()
        self._retry = retry_policy or RetryPolicy(
            attempts=config.retry_attempts,
            backoff_factor=config.retry_backoff_factor,
            max_backoff=config.retry_max_backoff,
        )
        self.logger = logger or logging.getLogger(f"carriers.{self.carrier_name}")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    # ------------------------------------------------------------------
    # Token lifecycle

    def _fetch_token(self) -> AccessToken:  # pragma: no cover - overridden
        raise NotImplementedError

    def get_access_token(self, *, force_refresh: bool = False) -> AccessToken:
        """Return a cached OAuth access token, refreshing when needed.

        The token is held in memory behind a lock and never written to disk.
        """

        with self._lock:
            if (
                not force_refresh
                and self._token
                and not self._token.is_expired(time.time(), self.config.token_refresh_margin)
            ):
                return self._token
            self.logger.debug("%s: requesting a new access token", self.carrier_name)
            self._token = self._fetch_token()
            return self._token

    def set_access_token(self, token: AccessToken) -> None:
        """Install a token obtained elsewhere (e.g. an auth-code flow)."""

        with self._lock:
            self._token = token

    # ------------------------------------------------------------------
    # Requests

    def default_headers(self, *, transaction_id: Optional[str] = None) -> Dict[str, str]:
        """Headers sent on every request. Carriers extend this."""

        return {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
            "Content-Type": "application/json",
        }

    def new_transaction_id(self) -> str:
        return uuid.uuid4().hex

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        query: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        authenticated: bool = True,
        transaction_id: Optional[str] = None,
        body: Optional[bytes] = None,
    ) -> CarrierResponse:
        """Send a request to any endpoint on this carrier."""

        if json_body is not None and body is not None:
            raise ValueError("Pass either json_body or body, not both.")

        request_headers: MutableMapping[str, str] = self.default_headers(
            transaction_id=transaction_id
        )
        if headers:
            request_headers.update({k: v for k, v in headers.items() if v is not None})
        if authenticated:
            token = self.get_access_token()
            request_headers["Authorization"] = f"{_bearer(token)} {token.value}"

        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")

        response = self._send(method, path, query=query, headers=request_headers, body=body)
        data = self._parse_response(response)
        return self.response_class(
            data=data,
            status_code=response.status_code,
            headers=response.headers,
            transaction_id=self._transaction_id(response.headers)
            or request_headers.get("transId")
            or request_headers.get("x-customer-transaction-id"),
        )

    def post(self, path: str, payload: Any, **kwargs: Any) -> CarrierResponse:
        return self.request("POST", path, json_body=payload, **kwargs)

    def put(self, path: str, payload: Any, **kwargs: Any) -> CarrierResponse:
        return self.request("PUT", path, json_body=payload, **kwargs)

    def patch(self, path: str, payload: Any, **kwargs: Any) -> CarrierResponse:
        return self.request("PATCH", path, json_body=payload, **kwargs)

    def get(
        self,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> CarrierResponse:
        return self.request("GET", path, query=query, **kwargs)

    def delete(
        self,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        payload: Optional[Any] = None,
        **kwargs: Any,
    ) -> CarrierResponse:
        return self.request("DELETE", path, query=query, json_body=payload, **kwargs)

    # ------------------------------------------------------------------
    # Transport, retry and error mapping

    def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Optional[bytes],
        query: Optional[Mapping[str, Any]] = None,
    ) -> HttpResponse:
        url = self._build_url(path, query)
        verb = method.upper()
        attempt = 1

        while True:
            try:
                response = self._transport.request(
                    verb,
                    url,
                    headers=headers,
                    body=body,
                    timeout=self.config.timeout,
                )
            except CarrierTransportError as exc:
                if self._retry.should_retry(attempt=attempt, method=verb, status_code=None):
                    delay = self._retry.delay_for(attempt=attempt)
                    self.logger.warning(
                        "%s %s failed to reach the carrier (%s); retrying in %.2fs "
                        "(attempt %d/%d)",
                        verb,
                        url,
                        exc,
                        delay,
                        attempt,
                        self._retry.attempts,
                    )
                    self._retry.sleep(delay)
                    attempt += 1
                    continue
                self.logger.error("%s %s failed to reach the carrier: %s", verb, url, exc)
                raise

            if response.status_code < 400:
                self.logger.debug("%s %s -> %d", verb, url, response.status_code)
                return response

            if self._retry.should_retry(
                attempt=attempt, method=verb, status_code=response.status_code
            ):
                delay = self._retry.delay_for(attempt=attempt, headers=response.headers)
                self.logger.warning(
                    "%s %s -> %d; retrying in %.2fs (attempt %d/%d)",
                    verb,
                    url,
                    response.status_code,
                    delay,
                    attempt,
                    self._retry.attempts,
                )
                self._retry.sleep(delay)
                attempt += 1
                continue

            raise self._build_error(response, method=verb, url=url)

    def _build_error(self, response: HttpResponse, *, method: str, url: str) -> CarrierAPIError:
        payload = self._safe_json(response)
        message = self._error_message(payload) or (
            f"{self.carrier_label} API error {response.status_code}."
        )
        error_type: Type[CarrierAPIError] = self.api_error_class
        if response.status_code in {400, 422}:
            error_type = self.validation_error_class
        elif response.status_code in {401, 403}:
            error_type = self.authentication_error_class
        elif response.status_code == 429:
            error_type = self.rate_limit_error_class
        transaction_id = self._transaction_id(response.headers)
        self.logger.error(
            "%s %s -> %d %s%s",
            method,
            url,
            response.status_code,
            message,
            f" (transaction {transaction_id})" if transaction_id else "",
        )
        return error_type(
            message,
            status_code=response.status_code,
            response=payload,
            headers=response.headers,
            transaction_id=transaction_id,
        )

    def _build_url(self, path: str, query: Optional[Mapping[str, Any]]) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            base = path
        else:
            base = f"{self.config.resolved_base_url}/{path.lstrip('/')}"
        if not query:
            return base
        # Drop unset optional parameters rather than sending "key=None".
        pairs = {key: value for key, value in query.items() if value is not None}
        if not pairs:
            return base
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode(pairs, doseq=True)}"

    def _parse_response(self, response: HttpResponse) -> Any:
        if not response.text:
            return None
        content_type = self._header(response.headers, "content-type") or ""
        if "json" in content_type.lower():
            return response.json()
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text

    def _safe_json(self, response: HttpResponse) -> Any:
        try:
            return self._parse_response(response)
        except json.JSONDecodeError:
            return response.text

    def _error_message(self, payload: Any) -> Optional[str]:
        """Flatten a carrier error body into one readable message."""

        if not isinstance(payload, Mapping):
            return None

        scopes: list[Any] = [payload]
        for key in self.error_envelope_keys:
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                scopes.append(nested)

        for scope in scopes:
            errors = scope.get("errors") or scope.get("Errors")
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)):
                messages = []
                for item in errors:
                    if isinstance(item, Mapping):
                        code = item.get("code") or item.get("Code")
                        message = item.get("message") or item.get("Message")
                        messages.append(
                            f"{code}: {message}" if code and message else str(message or code)
                        )
                messages = [message for message in messages if message and message != "None"]
                if messages:
                    return "; ".join(messages)

        for scope in scopes:
            for key in ("message", "error_description", "error"):
                value = scope.get(key)
                if value and not isinstance(value, (Mapping, list)):
                    return str(value)
        return None

    def _transaction_id(self, headers: Mapping[str, str]) -> Optional[str]:
        for name in self.transaction_id_headers:
            value = self._header(headers, name)
            if value:
                return value
        return None

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return None


def _bearer(token: AccessToken) -> str:
    """Normalise the token type for the Authorization header.

    UPS returns ``"Bearer"``, FedEx returns ``"bearer"``; both want the
    canonical capitalisation on the way back out.
    """

    return "Bearer" if token.token_type.lower() == "bearer" else token.token_type


def bool_str(value: bool, *, capitalize: bool = False) -> str:
    text = "true" if value else "false"
    return text.capitalize() if capitalize else text


__all__ = ["BaseClient", "JsonObject", "bool_str"]
