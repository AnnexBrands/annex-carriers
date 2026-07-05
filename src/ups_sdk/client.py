from __future__ import annotations

import base64
import json
import time
import uuid
from threading import RLock
from typing import Any, Mapping, MutableMapping, Optional, Sequence, Union
from urllib.parse import quote, urlencode

from .addresses import (
    VALIDATION_AND_CLASSIFICATION,
    build_address_validation_request,
)
from .config import UPSConfig
from .documents import (
    COMMERCIAL_INVOICE,
    FileSource,
    attach_paperless_documents,
    build_push_to_repository_request,
    build_upload_request,
    build_user_created_form,
    extract_document_ids,
    read_document_file,
)
from .errors import (
    UPSAPIError,
    UPSAuthenticationError,
    UPSRateLimitError,
    UPSValidationError,
)
from .models import AccessToken, UPSResponse
from .pickups import (
    CANCEL_BY_ACCOUNT,
    CANCEL_BY_PRN,
    build_pickup_rate_request,
    build_pickup_request,
)
from .rates import rate_request_from_ship_payload
from .transport import HttpResponse, Transport, UrlLibTransport

JsonObject = Mapping[str, Any]

# Default API versions per endpoint family (the current values in UPS's specs).
RATING_VERSION = "v2409"
SHIPPING_VERSION = "v2409"
PICKUP_VERSION = "v2409"
ADDRESS_VALIDATION_VERSION = "v2"
PAPERLESS_VERSION = "v2"
TIME_IN_TRANSIT_VERSION = "v1"
LABEL_RECOVERY_VERSION = "v1"


class UPSClient:
    """Synchronous client for UPS REST APIs.

    UPS API schemas are large and evolve over time, so SDK methods accept
    dictionaries matching UPS's request bodies and return parsed JSON.
    """

    def __init__(
        self,
        config: UPSConfig,
        *,
        transport: Optional[Transport] = None,
    ) -> None:
        self.config = config
        self._transport = transport or UrlLibTransport()
        self._token: Optional[AccessToken] = None
        self._lock = RLock()

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Optional[str] = None,
        transport: Optional[Transport] = None,
    ) -> "UPSClient":
        return cls(UPSConfig.from_env(env_file=env_file), transport=transport)

    def __enter__(self) -> "UPSClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def get_access_token(self, *, force_refresh: bool = False) -> AccessToken:
        """Return a cached OAuth access token, refreshing when needed."""

        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._token
                and not self._token.is_expired(now, self.config.token_refresh_margin)
            ):
                return self._token

            credentials = f"{self.config.client_id}:{self.config.client_secret}"
            headers = {
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic "
                + base64.b64encode(credentials.encode("utf-8")).decode("ascii"),
            }
            if self.config.account_number:
                headers["x-merchant-id"] = self.config.account_number

            response = self._send(
                "POST",
                "/security/v1/oauth/token",
                headers=headers,
                body=urlencode({"grant_type": self.config.grant_type}).encode("utf-8"),
            )
            payload = self._parse_response(response)
            if not isinstance(payload, Mapping) or "access_token" not in payload:
                raise UPSAuthenticationError(
                    "UPS OAuth response did not include an access token.",
                    status_code=response.status_code,
                    response=payload,
                    headers=response.headers,
                    transaction_id=self._transaction_id(response.headers),
                )

            # UPS returns numeric token fields as strings (e.g. "14399").
            expires_in = int(payload.get("expires_in") or 3600)
            self._token = AccessToken(
                value=str(payload["access_token"]),
                token_type=str(payload.get("token_type", "Bearer")),
                expires_at=time.time() + expires_in,
                scope=str(payload["scope"]) if payload.get("scope") else None,
            )
            return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[JsonObject] = None,
        query: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        authenticated: bool = True,
        transaction_id: Optional[str] = None,
        body: Optional[bytes] = None,
    ) -> UPSResponse:
        """Send a request to any UPS REST endpoint."""

        if json_body is not None and body is not None:
            raise ValueError("Pass either json_body or body, not both.")

        request_headers: MutableMapping[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
            "Content-Type": "application/json",
            "transId": transaction_id or uuid.uuid4().hex,
            "transactionSrc": self.config.transaction_src,
        }
        if headers:
            request_headers.update(headers)
        if authenticated:
            token = self.get_access_token()
            request_headers["Authorization"] = f"Bearer {token.value}"

        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")

        response = self._send(
            method,
            path,
            query=query,
            headers=request_headers,
            body=body,
        )
        data = self._parse_response(response)
        return UPSResponse(
            data=data,
            status_code=response.status_code,
            headers=response.headers,
            transaction_id=self._transaction_id(response.headers)
            or request_headers["transId"],
        )

    def post(
        self,
        path: str,
        payload: JsonObject,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.request("POST", path, json_body=payload, **kwargs)

    def get(
        self,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.request("GET", path, query=query, **kwargs)

    def delete(
        self,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.request("DELETE", path, query=query, **kwargs)

    # ------------------------------------------------------------------
    # Tracking

    def track(
        self,
        inquiry_number: str,
        *,
        locale: Optional[str] = None,
        return_signature: bool = False,
        return_milestones: bool = False,
        return_pod: bool = False,
        **kwargs: Any,
    ) -> UPSResponse:
        query: dict[str, str] = {
            "returnSignature": _bool_str(return_signature),
            "returnMilestones": _bool_str(return_milestones),
            "returnPOD": _bool_str(return_pod),
        }
        if locale:
            query["locale"] = locale
        return self.get(
            f"/api/track/v1/details/{quote(inquiry_number, safe='')}",
            query=query,
            **kwargs,
        )

    def track_by_reference(
        self,
        reference_number: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.get(
            f"/api/track/v1/reference/details/{quote(reference_number, safe='')}",
            query=query,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Rating and Time in Transit

    def rate(
        self,
        payload: JsonObject,
        *,
        request_option: str = "Rate",
        version: str = RATING_VERSION,
        additional_info: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {"additionalinfo": additional_info} if additional_info else None
        return self.post(
            f"/api/rating/{version}/{request_option}",
            payload,
            query=query,
            **kwargs,
        )

    def shop_rates(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.rate(payload, request_option="Shop", **kwargs)

    def rate_from_ship_payload(
        self,
        ship_payload: JsonObject,
        *,
        all_services: bool = False,
        negotiated_rates: Optional[bool] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        """Rate the exact payload that will be sent to ``create_shipment``."""
        return self.rate(
            rate_request_from_ship_payload(
                ship_payload,
                all_services=all_services,
                negotiated_rates=negotiated_rates,
            ),
            request_option="Shop" if all_services else "Rate",
            **kwargs,
        )

    def time_in_transit(
        self,
        payload: JsonObject,
        *,
        version: str = TIME_IN_TRANSIT_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.post(f"/api/shipments/{version}/transittimes", payload, **kwargs)

    # ------------------------------------------------------------------
    # Shipping

    def create_shipment(
        self,
        payload: JsonObject,
        *,
        version: str = SHIPPING_VERSION,
        additional_address_validation: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = (
            {"additionaladdressvalidation": additional_address_validation}
            if additional_address_validation
            else None
        )
        return self.post(f"/api/shipments/{version}/ship", payload, query=query, **kwargs)

    def void_shipment(
        self,
        shipment_identification_number: str,
        *,
        tracking_numbers: Optional[Sequence[str]] = None,
        version: str = SHIPPING_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Void a shipment, or specific packages when tracking numbers are given."""

        query: Optional[dict[str, str]] = None
        if tracking_numbers:
            numbers = list(tracking_numbers)
            # UPS expects one bare value, or a JSON-style list for multiple.
            query = {
                "trackingnumber": numbers[0]
                if len(numbers) == 1
                else json.dumps(numbers, separators=(",", ":"))
            }
        return self.delete(
            f"/api/shipments/{version}/void/cancel/"
            f"{quote(shipment_identification_number, safe='')}",
            query=query,
            **kwargs,
        )

    def recover_label(
        self,
        payload: JsonObject,
        *,
        version: str = LABEL_RECOVERY_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.post(f"/api/labels/{version}/recovery", payload, **kwargs)

    # ------------------------------------------------------------------
    # Address Validation

    def validate_addresses(
        self,
        payload: JsonObject,
        *,
        request_option: int = VALIDATION_AND_CLASSIFICATION,
        version: str = ADDRESS_VALIDATION_VERSION,
        regional_request_indicator: Optional[bool] = None,
        maximum_candidate_list_size: Optional[int] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query: dict[str, Any] = {}
        if regional_request_indicator is not None:
            query["regionalrequestindicator"] = _bool_str(
                regional_request_indicator, capitalize=True
            )
        if maximum_candidate_list_size is not None:
            query["maximumcandidatelistsize"] = int(maximum_candidate_list_size)
        return self.post(
            f"/api/addressvalidation/{version}/{request_option}",
            payload,
            query=query or None,
            **kwargs,
        )

    def validate_address(self, address: JsonObject, **kwargs: Any) -> UPSResponse:
        """Validate and classify a single Ship-shaped address dict."""
        return self.validate_addresses(build_address_validation_request(address), **kwargs)

    # ------------------------------------------------------------------
    # Pickups

    def rate_pickup(
        self,
        payload: JsonObject,
        *,
        pickup_type: str = "oncall",
        version: str = PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.post(f"/api/shipments/{version}/pickup/{pickup_type}", payload, **kwargs)

    def create_pickup(
        self,
        payload: JsonObject,
        *,
        version: str = PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.post(f"/api/pickupcreation/{version}/pickup", payload, **kwargs)

    def check_pickup_rate(
        self,
        pickup_address: JsonObject,
        *,
        pickup_date: str,
        ready_time: str = "0900",
        close_time: str = "1700",
        **kwargs: Any,
    ) -> UPSResponse:
        return self.rate_pickup(
            build_pickup_rate_request(
                pickup_address,
                pickup_date=pickup_date,
                ready_time=ready_time,
                close_time=close_time,
            ),
            **kwargs,
        )

    def schedule_pickup(
        self,
        *,
        pickup_address: JsonObject,
        pickup_date: str,
        ready_time: str = "0900",
        close_time: str = "1700",
        pieces: Sequence[JsonObject],
        total_weight_lb: Optional[float] = None,
        overweight: bool = False,
        payment_method: str = "01",
        rate_pickup: bool = False,
        special_instruction: Optional[str] = None,
        reference_number: Optional[str] = None,
        account_country_code: str = "US",
        **kwargs: Any,
    ) -> UPSResponse:
        return self.create_pickup(
            build_pickup_request(
                self.config.account_number or "",
                pickup_address=pickup_address,
                pickup_date=pickup_date,
                ready_time=ready_time,
                close_time=close_time,
                pieces=pieces,
                total_weight_lb=total_weight_lb,
                overweight=overweight,
                payment_method=payment_method,
                rate_pickup=rate_pickup,
                special_instruction=special_instruction,
                reference_number=reference_number,
                account_country_code=account_country_code,
            ),
            **kwargs,
        )

    def cancel_pickup(
        self,
        *,
        prn: Optional[str] = None,
        version: str = PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Cancel a scheduled pickup by PRN, or all pickups on the account."""

        cancel_by = CANCEL_BY_PRN if prn else CANCEL_BY_ACCOUNT
        headers = {"Prn": prn} if prn else None
        return self.delete(
            f"/api/shipments/{version}/pickup/{cancel_by}",
            headers=headers,
            **kwargs,
        )

    def pickup_pending_status(
        self,
        *,
        pickup_type: str = "oncall",
        account_number: Optional[str] = None,
        version: str = PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        account = account_number or self.config.account_number
        if not account:
            raise ValueError("account_number is required (or set it on UPSConfig).")
        return self.get(
            f"/api/shipments/{version}/pickup/{pickup_type}",
            headers={"AccountNumber": account},
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Paperless Documents

    def upload_paperless_document(
        self,
        attachment: FileSource,
        *,
        document_type: str = COMMERCIAL_INVOICE,
        filename: Optional[str] = None,
        file_format: Optional[str] = None,
        shipper_number: Optional[str] = None,
        customer_context: Optional[str] = None,
        version: str = PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Upload one trade document (base64 JSON) to UPS Forms History."""

        shipper = shipper_number or self.config.account_number
        if not shipper:
            raise ValueError("shipper_number is required (or set account_number on UPSConfig).")
        document = read_document_file(attachment, filename=filename, file_format=file_format)
        form = build_user_created_form(
            filename=document.filename,
            file_format=document.file_format,
            document_type=document_type,
            content=document.content,
        )
        return self.post(
            f"/api/paperlessdocuments/{version}/upload",
            build_upload_request(shipper, [form], customer_context=customer_context),
            headers={"ShipperNumber": shipper},
            **kwargs,
        )

    def upload_commercial_invoice(
        self,
        attachment: FileSource,
        *,
        filename: Optional[str] = None,
        file_format: Optional[str] = None,
        shipper_number: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.upload_paperless_document(
            attachment,
            document_type=COMMERCIAL_INVOICE,
            filename=filename,
            file_format=file_format,
            shipper_number=shipper_number,
            **kwargs,
        )

    def push_document_to_repository(
        self,
        *,
        document_ids: Sequence[str],
        shipment_identifier: str,
        shipment_date_and_time: str,
        tracking_number: Optional[str] = None,
        shipment_type: str = "1",
        shipper_number: Optional[str] = None,
        customer_context: Optional[str] = None,
        version: str = PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Associate uploaded documents with an already-created shipment."""

        shipper = shipper_number or self.config.account_number
        if not shipper:
            raise ValueError("shipper_number is required (or set account_number on UPSConfig).")
        return self.post(
            f"/api/paperlessdocuments/{version}/image",
            build_push_to_repository_request(
                shipper,
                document_ids=document_ids,
                shipment_identifier=shipment_identifier,
                shipment_date_and_time=shipment_date_and_time,
                shipment_type=shipment_type,
                tracking_number=tracking_number,
                customer_context=customer_context,
            ),
            headers={"ShipperNumber": shipper},
            **kwargs,
        )

    def delete_paperless_document(
        self,
        document_id: str,
        *,
        shipper_number: Optional[str] = None,
        version: str = PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        shipper = shipper_number or self.config.account_number
        if not shipper:
            raise ValueError("shipper_number is required (or set account_number on UPSConfig).")
        # The literal path segments are part of UPS's contract; the actual
        # identifiers travel in headers.
        return self.delete(
            f"/api/paperlessdocuments/{version}/DocumentId/ShipperNumber",
            headers={"DocumentId": document_id, "ShipperNumber": shipper},
            **kwargs,
        )

    def uploaded_document_ids(self, response: Union[UPSResponse, Any]) -> list[str]:
        data = response.data if isinstance(response, UPSResponse) else response
        return extract_document_ids(data)

    def uploaded_document_id(self, response: Union[UPSResponse, Any]) -> Optional[str]:
        ids = self.uploaded_document_ids(response)
        return ids[0] if ids else None

    def with_paperless_documents(
        self,
        ship_payload: JsonObject,
        document_ids: Sequence[str],
    ) -> dict[str, Any]:
        return attach_paperless_documents(ship_payload, document_ids)

    # ------------------------------------------------------------------

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
        response = self._transport.request(
            method.upper(),
            url,
            headers=headers,
            body=body,
            timeout=self.config.timeout,
        )
        if response.status_code >= 400:
            payload = self._safe_json(response)
            message = self._error_message(payload) or f"UPS API error {response.status_code}."
            error_type = UPSAPIError
            if response.status_code in {400, 422}:
                error_type = UPSValidationError
            elif response.status_code in {401, 403}:
                error_type = UPSAuthenticationError
            elif response.status_code == 429:
                error_type = UPSRateLimitError
            raise error_type(
                message,
                status_code=response.status_code,
                response=payload,
                headers=response.headers,
                transaction_id=self._transaction_id(response.headers),
            )
        return response

    def _build_url(self, path: str, query: Optional[Mapping[str, Any]]) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            base = path
        else:
            base = f"{self.config.resolved_base_url}/{path.lstrip('/')}"
        if not query:
            return base
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode(query, doseq=True)}"

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
        if isinstance(payload, Mapping):
            errors = (payload.get("response") or {}).get("errors") if isinstance(
                payload.get("response"), Mapping
            ) else payload.get("errors")
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)):
                messages = []
                for item in errors:
                    if isinstance(item, Mapping):
                        code = item.get("code")
                        message = item.get("message")
                        messages.append(
                            f"{code}: {message}" if code and message else str(message or code)
                        )
                messages = [message for message in messages if message]
                if messages:
                    return "; ".join(messages)
            for key in ("message", "error_description", "error"):
                value = payload.get(key)
                if value:
                    return str(value)
        return None

    def _transaction_id(self, headers: Mapping[str, str]) -> Optional[str]:
        return self._header(headers, "transId")

    def _header(self, headers: Mapping[str, str], name: str) -> Optional[str]:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return None


def _bool_str(value: bool, *, capitalize: bool = False) -> str:
    text = "true" if value else "false"
    return text.capitalize() if capitalize else text
