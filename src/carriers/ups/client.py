"""The UPS client.

Everything carrier-agnostic — transport, retry, token caching, error mapping,
logging — lives in ``carriers._core``. What remains here is UPS's own OAuth
shape (Basic auth plus ``x-merchant-id``), its two required headers, and the
namespaces that group its nineteen API families.

The namespaced surface is the one to write new code against::

    client.rating.shop(payload)
    client.paperless.upload("invoice.pdf")
    client.trade.landed_cost(...)

The flat methods below it (``client.rate``, ``client.track``, …) are the 0.1
surface kept working; they delegate straight to the namespaces.
"""
from __future__ import annotations

import base64
import time
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence, Union
from urllib.parse import urlencode

from .._core.client import BaseClient
from .._core.resources import resource
from . import endpoints
from .config import UPSConfig
from .errors import (
    UPSAPIError,
    UPSAuthenticationError,
    UPSRateLimitError,
    UPSValidationError,
)
from .models import AccessToken, UPSResponse
from .resources import (
    AddressesResource,
    DangerousGoodsResource,
    ForwardingResource,
    OAuthResource,
    PaperlessResource,
    PickupsResource,
    RatingResource,
    ShippingResource,
    TrackingResource,
    TradeResource,
    VisibilityResource,
)

JsonObject = Mapping[str, Any]

# Re-exported so callers that imported them from this module keep working.
RATING_VERSION = endpoints.RATING_VERSION
SHIPPING_VERSION = endpoints.SHIPPING_VERSION
PICKUP_VERSION = endpoints.PICKUP_VERSION
ADDRESS_VALIDATION_VERSION = endpoints.ADDRESS_VALIDATION_VERSION
PAPERLESS_VERSION = endpoints.PAPERLESS_VERSION
TIME_IN_TRANSIT_VERSION = endpoints.TIME_IN_TRANSIT_VERSION
LABEL_RECOVERY_VERSION = endpoints.LABEL_RECOVERY_VERSION


class UPSClient(BaseClient):
    """Synchronous client for UPS REST APIs.

    UPS API schemas are large and evolve over time, so SDK methods accept
    dictionaries matching UPS's request bodies and return parsed JSON.
    """

    carrier_name = "ups"
    carrier_label = "UPS"
    api_error_class = UPSAPIError
    authentication_error_class = UPSAuthenticationError
    rate_limit_error_class = UPSRateLimitError
    validation_error_class = UPSValidationError
    response_class = UPSResponse
    transaction_id_headers = ("transId",)
    # UPS nests its error array one level down, under "response".
    error_envelope_keys = ("response",)

    config: UPSConfig

    # --- namespaces ----------------------------------------------------
    oauth = resource(OAuthResource)
    tracking = resource(TrackingResource)
    rating = resource(RatingResource)
    shipping = resource(ShippingResource)
    addresses = resource(AddressesResource)
    pickups = resource(PickupsResource)
    paperless = resource(PaperlessResource)
    trade = resource(TradeResource)
    visibility = resource(VisibilityResource)
    dangerous_goods = resource(DangerousGoodsResource)
    forwarding = resource(ForwardingResource)

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Optional[str] = None,
        **kwargs: Any,
    ) -> "UPSClient":
        return cls(UPSConfig.from_env(env_file=env_file), **kwargs)

    def __enter__(self) -> "UPSClient":
        return self

    # ------------------------------------------------------------------
    # Auth

    def default_headers(self, *, transaction_id: Optional[str] = None) -> Dict[str, str]:
        headers = super().default_headers(transaction_id=transaction_id)
        headers["transId"] = transaction_id or uuid.uuid4().hex
        headers["transactionSrc"] = self.config.transaction_src
        return headers

    def _fetch_token(self) -> AccessToken:
        return self._token_request(
            endpoints.OAUTH_TOKEN, {"grant_type": self.config.grant_type}
        )

    def _token_request(self, path: str, data: Mapping[str, str]) -> AccessToken:
        """Run one OAuth exchange and parse the token out of it.

        Shared by the client-credentials grant and the authorization-code
        flow in :class:`~carriers.ups.resources.OAuthResource`; both use HTTP
        Basic auth with the app's client id and secret.
        """

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
            path,
            headers=headers,
            body=urlencode(dict(data)).encode("utf-8"),
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
        return AccessToken(
            value=str(payload["access_token"]),
            token_type=str(payload.get("token_type", "Bearer")),
            expires_at=time.time() + expires_in,
            scope=str(payload["scope"]) if payload.get("scope") else None,
            refresh_token=str(payload["refresh_token"])
            if payload.get("refresh_token")
            else None,
        )

    # ------------------------------------------------------------------
    # Flat convenience methods (0.1 surface). Each forwards to a namespace.

    def track(self, inquiry_number: str, **kwargs: Any) -> UPSResponse:
        return self.tracking.track(inquiry_number, **kwargs)

    def track_by_reference(self, reference_number: str, **kwargs: Any) -> UPSResponse:
        return self.tracking.track_by_reference(reference_number, **kwargs)

    def rate(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.rating.rate(payload, **kwargs)

    def shop_rates(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.rating.shop(payload, **kwargs)

    def rate_from_ship_payload(self, ship_payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.rating.from_ship_payload(ship_payload, **kwargs)

    def time_in_transit(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.rating.time_in_transit(payload, **kwargs)

    def create_shipment(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.shipping.create(payload, **kwargs)

    def void_shipment(
        self, shipment_identification_number: str, **kwargs: Any
    ) -> UPSResponse:
        return self.shipping.void(shipment_identification_number, **kwargs)

    def recover_label(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.shipping.recover_label(payload, **kwargs)

    def validate_addresses(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.addresses.validate_payload(payload, **kwargs)

    def validate_address(self, address: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.addresses.validate(address, **kwargs)

    def rate_pickup(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.pickups.rate_payload(payload, **kwargs)

    def create_pickup(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.pickups.create_payload(payload, **kwargs)

    def check_pickup_rate(self, pickup_address: JsonObject, **kwargs: Any) -> UPSResponse:
        return self.pickups.rate(pickup_address, **kwargs)

    def schedule_pickup(self, **kwargs: Any) -> UPSResponse:
        return self.pickups.schedule(**kwargs)

    def cancel_pickup(self, **kwargs: Any) -> UPSResponse:
        return self.pickups.cancel(**kwargs)

    def pickup_pending_status(self, **kwargs: Any) -> UPSResponse:
        return self.pickups.pending_status(**kwargs)

    def upload_paperless_document(self, attachment: Any, **kwargs: Any) -> UPSResponse:
        return self.paperless.upload(attachment, **kwargs)

    def upload_commercial_invoice(self, attachment: Any, **kwargs: Any) -> UPSResponse:
        return self.paperless.upload_commercial_invoice(attachment, **kwargs)

    def push_document_to_repository(self, **kwargs: Any) -> UPSResponse:
        return self.paperless.push_to_repository(**kwargs)

    def delete_paperless_document(self, document_id: str, **kwargs: Any) -> UPSResponse:
        return self.paperless.delete(document_id, **kwargs)

    def uploaded_document_ids(self, response: Union[UPSResponse, Any]) -> list:
        return self.paperless.document_ids(response)

    def uploaded_document_id(self, response: Union[UPSResponse, Any]) -> Optional[str]:
        return self.paperless.document_id(response)

    def with_paperless_documents(
        self, ship_payload: JsonObject, document_ids: Sequence[str]
    ) -> Dict[str, Any]:
        return self.paperless.attach(ship_payload, document_ids)


__all__ = ["UPSClient"]
