"""The FedEx client.

Everything carrier-agnostic — transport, retry, token caching, error mapping,
logging — lives in ``carriers._core``. What remains here is FedEx's own OAuth
body shape (form-encoded, with optional child credentials) and the namespaces
that group its API families.

The namespaced surface is the one to write new code against::

    client.ship.create(payload)
    client.documents.upload_post_shipment(invoice, ...)
    client.track.by_tracking_numbers(["1234"])

The flat methods below it are the 0.1 surface kept working.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Union
from urllib.parse import urlencode

from .._core.client import BaseClient
from .._core.resources import resource
from . import endpoints
from .config import FedExConfig
from .documents import (
    COMMERCIAL_INVOICE,
    POSTSHIPMENT_WORKFLOW,
    PRESHIPMENT_WORKFLOW,
    FileSource,
)
from .errors import (
    FedExAPIError,
    FedExAuthenticationError,
    FedExRateLimitError,
    FedExValidationError,
)
from .models import AccessToken, FedExResponse
from .resources import (
    AddressesResource,
    AvailabilityResource,
    DocumentsResource,
    LocationsResource,
    PickupsResource,
    RateResource,
    ShipResource,
    TrackResource,
)

JsonObject = Mapping[str, Any]


class FedExClient(BaseClient):
    """Synchronous client for FedEx REST APIs.

    FedEx API schemas are large and evolve over time, so SDK methods accept
    dictionaries matching FedEx's request bodies and return parsed JSON.
    """

    carrier_name = "fedex"
    carrier_label = "FedEx"
    api_error_class = FedExAPIError
    authentication_error_class = FedExAuthenticationError
    rate_limit_error_class = FedExRateLimitError
    validation_error_class = FedExValidationError
    response_class = FedExResponse
    transaction_id_headers = ("x-customer-transaction-id", "x-fedex-transaction-id")
    # FedEx puts its error array at the top level; "output" is checked as a
    # fallback because some families report alerts there instead.
    error_envelope_keys = ("output",)

    config: FedExConfig

    # --- namespaces ----------------------------------------------------
    ship = resource(ShipResource)
    rate = resource(RateResource)
    track = resource(TrackResource)
    addresses = resource(AddressesResource)
    locations = resource(LocationsResource)
    pickups = resource(PickupsResource)
    documents = resource(DocumentsResource)
    availability = resource(AvailabilityResource)

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Optional[str] = None,
        **kwargs: Any,
    ) -> "FedExClient":
        return cls(FedExConfig.from_env(env_file=env_file), **kwargs)

    def __enter__(self) -> "FedExClient":
        return self

    # ------------------------------------------------------------------
    # Auth

    def default_headers(self, *, transaction_id: Optional[str] = None) -> Dict[str, str]:
        headers = super().default_headers(transaction_id=transaction_id)
        headers["x-customer-transaction-id"] = transaction_id or self.new_transaction_id()
        return headers

    def _fetch_token(self) -> AccessToken:
        data: MutableMapping[str, str] = {
            "grant_type": self.config.grant_type,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        if self.config.child_key:
            data["child_key"] = self.config.child_key
        if self.config.child_secret:
            data["child_secret"] = self.config.child_secret

        response = self._send(
            "POST",
            endpoints.OAUTH_TOKEN,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(data).encode("utf-8"),
        )
        payload = self._parse_response(response)
        if not isinstance(payload, Mapping) or "access_token" not in payload:
            raise FedExAuthenticationError(
                "FedEx OAuth response did not include an access token.",
                status_code=response.status_code,
                response=payload,
                headers=response.headers,
                transaction_id=self._transaction_id(response.headers),
            )

        expires_in = int(payload.get("expires_in", 3600))
        return AccessToken(
            value=str(payload["access_token"]),
            token_type=str(payload.get("token_type", "bearer")),
            expires_at=time.time() + expires_in,
            scope=str(payload["scope"]) if payload.get("scope") else None,
        )

    def request(self, method: str, path: str, *, locale: Optional[str] = None, **kwargs: Any):
        """FedEx accepts an ``X-locale`` header for localised messages."""

        if locale:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-locale", locale)
            kwargs["headers"] = headers
        return super().request(method, path, **kwargs)

    # ------------------------------------------------------------------
    # Flat convenience methods (0.1 surface). Each forwards to a namespace.

    def track_by_tracking_numbers(
        self, tracking_numbers: Sequence[str], **kwargs: Any
    ) -> FedExResponse:
        return self.track.by_tracking_numbers(tracking_numbers, **kwargs)

    def rate_quotes(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.rate.quotes(payload, **kwargs)

    def create_shipment(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.ship.create(payload, **kwargs)

    def validate_shipment(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.ship.validate(payload, **kwargs)

    def cancel_shipment(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.ship.cancel(payload, **kwargs)

    def validate_addresses(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.addresses.resolve(payload, **kwargs)

    def validate_address(self, address: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.addresses.validate(address, **kwargs)

    def rate_from_ship_payload(
        self, ship_payload: JsonObject, **kwargs: Any
    ) -> FedExResponse:
        return self.rate.from_ship_payload(ship_payload, **kwargs)

    def find_locations(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.locations.search(payload, **kwargs)

    def pickup_availability(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.pickups.availability(payload, **kwargs)

    def create_pickup(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.pickups.create(payload, **kwargs)

    def cancel_pickup(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self.pickups.cancel(payload, **kwargs)

    def check_pickup_availability(
        self, pickup_address: JsonObject, **kwargs: Any
    ) -> FedExResponse:
        return self.pickups.check_availability(pickup_address, **kwargs)

    def schedule_pickup(self, **kwargs: Any) -> FedExResponse:
        return self.pickups.schedule(**kwargs)

    def cancel_scheduled_pickup(self, **kwargs: Any) -> FedExResponse:
        return self.pickups.cancel_scheduled(**kwargs)

    def upload_etd_document(
        self, document: JsonObject, attachment: FileSource, **kwargs: Any
    ) -> FedExResponse:
        return self.documents.upload_document(document, attachment, **kwargs)

    def upload_commercial_invoice(
        self,
        attachment: FileSource,
        *,
        origin_country_code: str,
        destination_country_code: str,
        workflow_name: str = PRESHIPMENT_WORKFLOW,
        **kwargs: Any,
    ) -> FedExResponse:
        return self.documents.upload_etd(
            attachment,
            origin_country_code=origin_country_code,
            destination_country_code=destination_country_code,
            document_type=COMMERCIAL_INVOICE,
            workflow_name=workflow_name,
            **kwargs,
        )

    def upload_post_shipment_commercial_invoice(
        self, attachment: FileSource, **kwargs: Any
    ) -> FedExResponse:
        return self.documents.upload_post_shipment(attachment, **kwargs)

    def commercial_invoice_reference(self, document_id: str, **kwargs: Any) -> dict:
        return self.documents.reference(document_id, **kwargs)

    def uploaded_document_id(self, response: Union[FedExResponse, Any]) -> Optional[str]:
        return self.documents.document_id(response)

    def with_pre_shipment_documents(
        self,
        shipment_payload: JsonObject,
        documents: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> dict:
        return self.documents.attach_to_shipment(shipment_payload, documents, **kwargs)


__all__ = ["FedExClient", "POSTSHIPMENT_WORKFLOW", "PRESHIPMENT_WORKFLOW"]
