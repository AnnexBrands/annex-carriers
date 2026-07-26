"""Namespaced UPS API surfaces: ``client.rating.shop(...)``, ``client.trade.landed_cost(...)``.

One resource per UPS API family, each mapping to a Postman collection in
``docs/postman/ups/``. Methods take the plain dictionaries UPS documents, so a
schema change on UPS's side does not require a release here; the builders in
``rates``, ``pickups``, ``addresses``, ``documents``, ``trade`` and
``forwarding`` cover the shapes that are tedious or easy to get wrong.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional, Sequence, Union
from urllib.parse import quote

from .._core.client import bool_str
from .._core.resources import Resource
from . import endpoints
from .addresses import VALIDATION_AND_CLASSIFICATION, build_address_validation_request
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
from .forwarding import forwarding_headers, json_patch
from .models import AccessToken, UPSResponse
from .oauth import authorization_url
from .pickups import CANCEL_BY_ACCOUNT, CANCEL_BY_PRN, build_pickup_rate_request, build_pickup_request
from .rates import rate_request_from_ship_payload
from .tracking import build_track_alert_subscription
from .trade import ACTION_VALIDATE, build_customs_detail_request, build_landed_cost_request

JsonObject = Mapping[str, Any]


class OAuthResource(Resource):
    """The authorization-code grant.

    The client-credentials grant is automatic — every authenticated call
    fetches and caches its own token. These methods exist for the interactive
    flow, where a UPS account holder grants your app access in a browser.
    """

    def authorization_url(
        self,
        *,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
        scope: Optional[Sequence[str]] = None,
    ) -> str:
        return authorization_url(
            self.config, redirect_uri=redirect_uri, state=state, scope=scope
        )

    def exchange_authorization_code(
        self,
        code: str,
        *,
        redirect_uri: Optional[str] = None,
        install: bool = True,
    ) -> AccessToken:
        """Trade an authorization code for an access token.

        ``install=True`` (the default) stores the token on the client, so
        subsequent calls use the account holder's authorisation rather than
        the app's own client-credentials token.
        """

        target = redirect_uri or self.config.redirect_uri
        if not target:
            raise ValueError("redirect_uri is required (or set it on UPSConfig).")
        token = self._client._token_request(
            endpoints.OAUTH_TOKEN,
            {"grant_type": "authorization_code", "code": code, "redirect_uri": target},
        )
        if install:
            self._client.set_access_token(token)
        return token

    def refresh(self, refresh_token: str, *, install: bool = True) -> AccessToken:
        """Exchange a refresh token for a fresh access token."""

        token = self._client._token_request(
            endpoints.OAUTH_REFRESH,
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        if install:
            self._client.set_access_token(token)
        return token


class TrackingResource(Resource):
    """Tracking and Track Alert (webhook subscriptions)."""

    def track(
        self,
        inquiry_number: str,
        *,
        locale: Optional[str] = None,
        return_signature: bool = False,
        return_milestones: bool = False,
        return_pod: bool = False,
        version: str = endpoints.TRACK_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        query: dict[str, Any] = {
            "returnSignature": bool_str(return_signature),
            "returnMilestones": bool_str(return_milestones),
            "returnPOD": bool_str(return_pod),
        }
        if locale:
            query["locale"] = locale
        path = endpoints.TRACK_DETAILS.format(
            version=version, inquiry_number=quote(inquiry_number, safe="")
        )
        return self._client.get(path, query=query, **kwargs)

    def track_by_reference(
        self,
        reference_number: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        version: str = endpoints.TRACK_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        path = endpoints.TRACK_REFERENCE_DETAILS.format(
            version=version, reference_number=quote(reference_number, safe="")
        )
        return self._client.get(path, query=query, **kwargs)

    def subscribe(
        self,
        tracking_numbers: Sequence[str],
        *,
        destination_url: str,
        credential: str,
        enhanced: bool = False,
        version: str = endpoints.TRACK_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Register a Track Alert webhook for a list of tracking numbers."""

        payload = build_track_alert_subscription(
            tracking_numbers,
            destination_url=destination_url,
            credential=credential,
        )
        return self.subscribe_payload(payload, enhanced=enhanced, version=version, **kwargs)

    def subscribe_payload(
        self,
        payload: JsonObject,
        *,
        enhanced: bool = False,
        version: str = endpoints.TRACK_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        template = (
            endpoints.TRACK_ALERT_ENHANCED if enhanced else endpoints.TRACK_ALERT_STANDARD
        )
        return self._client.post(template.format(version=version), payload, **kwargs)


class RatingResource(Resource):
    """Rating and Time in Transit."""

    def rate(
        self,
        payload: JsonObject,
        *,
        request_option: str = "Rate",
        version: str = endpoints.RATING_VERSION,
        additional_info: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {"additionalinfo": additional_info} if additional_info else None
        path = endpoints.RATING.format(version=version, request_option=request_option)
        return self._client.post(path, payload, query=query, **kwargs)

    def shop(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        """Rate every service UPS can quote for the shipment."""
        return self.rate(payload, request_option="Shop", **kwargs)

    def rate_with_time_in_transit(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        """Rate and return transit times in one call."""
        return self.rate(payload, additional_info="timeintransit", **kwargs)

    def from_ship_payload(
        self,
        ship_payload: JsonObject,
        *,
        all_services: bool = False,
        negotiated_rates: Optional[bool] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        """Rate the exact payload that will be sent to ``shipping.create``."""

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
        version: str = endpoints.TIME_IN_TRANSIT_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.TIME_IN_TRANSIT.format(version=version), payload, **kwargs
        )


class ShippingResource(Resource):
    """Shipping, voids and label recovery."""

    def create(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.SHIPPING_VERSION,
        additional_address_validation: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = (
            {"additionaladdressvalidation": additional_address_validation}
            if additional_address_validation
            else None
        )
        return self._client.post(
            endpoints.SHIP.format(version=version), payload, query=query, **kwargs
        )

    def void(
        self,
        shipment_identification_number: str,
        *,
        tracking_numbers: Optional[Sequence[str]] = None,
        version: str = endpoints.SHIPPING_VERSION,
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
        path = endpoints.VOID_SHIPMENT.format(
            version=version, shipment_id=quote(shipment_identification_number, safe="")
        )
        return self._client.delete(path, query=query, **kwargs)

    def recover_label(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.LABEL_RECOVERY_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.LABEL_RECOVERY.format(version=version), payload, **kwargs
        )


class AddressesResource(Resource):
    """Address Validation (XAV)."""

    def validate_payload(
        self,
        payload: JsonObject,
        *,
        request_option: int = VALIDATION_AND_CLASSIFICATION,
        version: str = endpoints.ADDRESS_VALIDATION_VERSION,
        regional_request_indicator: Optional[bool] = None,
        maximum_candidate_list_size: Optional[int] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query: dict[str, Any] = {}
        if regional_request_indicator is not None:
            query["regionalrequestindicator"] = bool_str(
                regional_request_indicator, capitalize=True
            )
        if maximum_candidate_list_size is not None:
            query["maximumcandidatelistsize"] = int(maximum_candidate_list_size)
        path = endpoints.ADDRESS_VALIDATION.format(
            version=version, request_option=request_option
        )
        return self._client.post(path, payload, query=query or None, **kwargs)

    def validate(self, address: JsonObject, **kwargs: Any) -> UPSResponse:
        """Validate and classify a single Ship-shaped address dict."""
        return self.validate_payload(build_address_validation_request(address), **kwargs)


class PickupsResource(Resource):
    """On-call pickups, plus the country and service-centre lookups."""

    def rate_payload(
        self,
        payload: JsonObject,
        *,
        pickup_type: str = "oncall",
        version: str = endpoints.PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        path = endpoints.PICKUP_RATE.format(version=version, pickup_type=pickup_type)
        return self._client.post(path, payload, **kwargs)

    def rate(
        self,
        pickup_address: JsonObject,
        *,
        pickup_date: str,
        ready_time: str = "0900",
        close_time: str = "1700",
        **kwargs: Any,
    ) -> UPSResponse:
        return self.rate_payload(
            build_pickup_rate_request(
                pickup_address,
                pickup_date=pickup_date,
                ready_time=ready_time,
                close_time=close_time,
            ),
            **kwargs,
        )

    def create_payload(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.PICKUP_CREATE.format(version=version), payload, **kwargs
        )

    def schedule(
        self,
        *,
        pickup_address: JsonObject,
        pickup_date: str,
        pieces: Sequence[JsonObject],
        ready_time: str = "0900",
        close_time: str = "1700",
        total_weight_lb: Optional[float] = None,
        overweight: bool = False,
        payment_method: str = "01",
        rate_pickup: bool = False,
        special_instruction: Optional[str] = None,
        reference_number: Optional[str] = None,
        account_country_code: str = "US",
        **kwargs: Any,
    ) -> UPSResponse:
        return self.create_payload(
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

    def cancel(
        self,
        *,
        prn: Optional[str] = None,
        version: str = endpoints.PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Cancel a scheduled pickup by PRN, or all pickups on the account."""

        cancel_by = CANCEL_BY_PRN if prn else CANCEL_BY_ACCOUNT
        headers = {"Prn": prn} if prn else None
        path = endpoints.PICKUP_CANCEL.format(version=version, cancel_by=cancel_by)
        return self._client.delete(path, headers=headers, **kwargs)

    def pending_status(
        self,
        *,
        pickup_type: str = "oncall",
        account_number: Optional[str] = None,
        version: str = endpoints.PICKUP_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        account = account_number or self.config.account_number
        if not account:
            raise ValueError("account_number is required (or set it on UPSConfig).")
        path = endpoints.PICKUP_PENDING.format(version=version, pickup_type=pickup_type)
        return self._client.get(path, headers={"AccountNumber": account}, **kwargs)

    def political_divisions(
        self,
        country_code: str,
        *,
        version: str = endpoints.PICKUP_INFO_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """List the states/provinces UPS recognises for a country."""

        path = endpoints.PICKUP_POLITICAL_DIVISIONS.format(
            version=version, country_code=quote(country_code, safe="")
        )
        return self._client.get(path, **kwargs)

    def service_centers(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.PICKUP_INFO_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Find drop-off facilities for a freight pickup."""

        return self._client.post(
            endpoints.PICKUP_SERVICE_CENTERS.format(version=version), payload, **kwargs
        )


class PaperlessResource(Resource):
    """Paperless Documents: upload, associate with a shipment, delete."""

    def upload(
        self,
        attachment: FileSource,
        *,
        document_type: str = COMMERCIAL_INVOICE,
        filename: Optional[str] = None,
        file_format: Optional[str] = None,
        shipper_number: Optional[str] = None,
        customer_context: Optional[str] = None,
        version: str = endpoints.PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Upload one trade document (base64 JSON) to UPS Forms History."""

        shipper = self._shipper(shipper_number)
        document = read_document_file(attachment, filename=filename, file_format=file_format)
        form = build_user_created_form(
            filename=document.filename,
            file_format=document.file_format,
            document_type=document_type,
            content=document.content,
        )
        return self._client.post(
            endpoints.PAPERLESS_UPLOAD.format(version=version),
            build_upload_request(shipper, [form], customer_context=customer_context),
            headers={"ShipperNumber": shipper},
            **kwargs,
        )

    def upload_commercial_invoice(
        self,
        attachment: FileSource,
        **kwargs: Any,
    ) -> UPSResponse:
        return self.upload(attachment, document_type=COMMERCIAL_INVOICE, **kwargs)

    def push_to_repository(
        self,
        *,
        document_ids: Sequence[str],
        shipment_identifier: str,
        shipment_date_and_time: str,
        tracking_number: Optional[str] = None,
        shipment_type: str = "1",
        shipper_number: Optional[str] = None,
        customer_context: Optional[str] = None,
        version: str = endpoints.PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Associate uploaded documents with an already-created shipment."""

        shipper = self._shipper(shipper_number)
        return self._client.post(
            endpoints.PAPERLESS_PUSH_IMAGE.format(version=version),
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

    def delete(
        self,
        document_id: str,
        *,
        shipper_number: Optional[str] = None,
        version: str = endpoints.PAPERLESS_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        shipper = self._shipper(shipper_number)
        return self._client.delete(
            endpoints.PAPERLESS_DELETE.format(version=version),
            headers={"DocumentId": document_id, "ShipperNumber": shipper},
            **kwargs,
        )

    def document_ids(self, response: Union[UPSResponse, Any]) -> list[str]:
        data = response.data if isinstance(response, UPSResponse) else response
        return extract_document_ids(data)

    def document_id(self, response: Union[UPSResponse, Any]) -> Optional[str]:
        ids = self.document_ids(response)
        return ids[0] if ids else None

    def attach(
        self,
        ship_payload: JsonObject,
        document_ids: Sequence[str],
    ) -> dict[str, Any]:
        return attach_paperless_documents(ship_payload, document_ids)

    def _shipper(self, shipper_number: Optional[str]) -> str:
        shipper = shipper_number or self.config.account_number
        if not shipper:
            raise ValueError(
                "shipper_number is required (or set account_number on UPSConfig)."
            )
        return shipper


class TradeResource(Resource):
    """Landed Cost, Customs Detail and both Export Assure APIs."""

    def landed_cost_payload(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.LANDED_COST_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.LANDED_COST_QUOTES.format(version=version), payload, **kwargs
        )

    def landed_cost(
        self,
        *,
        shipment_id: str,
        import_country_code: str,
        export_country_code: str,
        items: Sequence[JsonObject],
        currency_code: str = "USD",
        **kwargs: Any,
    ) -> UPSResponse:
        """Quote duties, taxes and fees for an international shipment."""

        builder_keys = {
            "transaction_id",
            "import_province",
            "ship_date",
            "incoterms",
            "transport_mode",
            "allow_partial_result",
            "shipment_extras",
        }
        builder_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in builder_keys}
        payload = build_landed_cost_request(
            shipment_id=shipment_id,
            import_country_code=import_country_code,
            export_country_code=export_country_code,
            items=items,
            currency_code=currency_code,
            **builder_kwargs,
        )
        return self.landed_cost_payload(payload, **kwargs)

    def customs_detail_fields(
        self,
        *,
        import_country_code: str,
        export_country_code: str,
        commodity_codes: Optional[Sequence[str]] = None,
        locale: Optional[str] = None,
        version: str = endpoints.CUSTOMS_DETAIL_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Ask UPS which customs fields this lane requires."""

        query: dict[str, Any] = {
            "import_country_code": import_country_code,
            "export_country_code": export_country_code,
        }
        if locale:
            query["locale"] = locale
        if commodity_codes:
            query["commodity_codes"] = ",".join(commodity_codes)
        return self._client.get(
            endpoints.CUSTOMS_DETAIL.format(version=version), query=query, **kwargs
        )

    def submit_customs_detail(
        self,
        *,
        shipment_metadata: Sequence[JsonObject],
        shipper_number: Optional[str] = None,
        action_type: str = ACTION_VALIDATE,
        tracking_number: Optional[str] = None,
        version: str = endpoints.CUSTOMS_DETAIL_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Validate or save customs field values for a shipment."""

        shipper = shipper_number or self.config.account_number
        if not shipper:
            raise ValueError(
                "shipper_number is required (or set account_number on UPSConfig)."
            )
        payload = build_customs_detail_request(
            shipper_number=shipper,
            shipment_metadata=shipment_metadata,
            action_type=action_type,
            tracking_number=tracking_number,
        )
        return self._client.post(
            endpoints.CUSTOMS_DETAIL.format(version=version), payload, **kwargs
        )

    def export_assure_compliance(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        """Commodity compliance guidance for an export."""
        return self._client.post(endpoints.EXPORT_ASSURE_COMPLIANCE, payload, **kwargs)

    def export_assure_interactive(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        """Interactive description-of-goods refinement."""
        return self._client.post(endpoints.EXPORT_ASSURE_INTERACTIVE, payload, **kwargs)


class VisibilityResource(Resource):
    """Quantum View, Delivery Intercept and DeliveryDefense."""

    def quantum_view_events(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.QUANTUM_VIEW_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.QUANTUM_VIEW_EVENTS.format(version=version), payload, **kwargs
        )

    def intercept_charges(
        self,
        tracking_number: str,
        payload: JsonObject,
        *,
        version: str = endpoints.DELIVERY_INTERCEPT_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        """Quote the charge for redirecting or holding an in-transit package."""

        path = endpoints.DELIVERY_INTERCEPT_CHARGES.format(
            version=version, tracking_number=quote(tracking_number, safe="")
        )
        return self._client.post(path, payload, **kwargs)

    def address_confidence(
        self,
        *,
        street: str,
        city: str,
        state: str,
        zip_code: str,
        **kwargs: Any,
    ) -> UPSResponse:
        """DeliveryDefense score for how likely an address is to deliver cleanly."""

        payload = {"street": street, "city": city, "state": state, "zipCode": zip_code}
        return self._client.post(endpoints.DELIVERY_DEFENSE_SCORE, payload, **kwargs)


class DangerousGoodsResource(Resource):
    """Hazmat pre-notification."""

    def pre_notification(
        self,
        payload: JsonObject,
        *,
        version: str = endpoints.PRE_NOTIFICATION_VERSION,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._client.post(
            endpoints.PRE_NOTIFICATION.format(version=version), payload, **kwargs
        )


class ForwardingResource(Resource):
    """UPS Forwarding: freight orders, shipments, quotes and reference data.

    Every method accepts ``business_guid=`` and ``client_id=`` for the two
    Forwarding-only headers; set them once on the resource with
    :meth:`configure` to avoid repeating them.
    """

    _business_guid: Optional[str] = None
    _client_id: Optional[str] = None

    def configure(
        self,
        *,
        business_guid: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> "ForwardingResource":
        if business_guid is not None:
            self._business_guid = business_guid
        if client_id is not None:
            self._client_id = client_id
        return self

    # --- orders ------------------------------------------------------
    def create_order(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_ORDERS, payload, **kwargs)

    def cancel_order(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._request("DELETE", endpoints.FORWARDING_ORDERS, payload=payload, **kwargs)

    def update_order_date(
        self,
        operations: Sequence[JsonObject],
        *,
        shipper_account_number: str,
        order_number: str,
        old_date: str,
        language: str = "en-US",
        **kwargs: Any,
    ) -> UPSResponse:
        # UPS's own parameter name carries a typo ("shippper"); the server
        # reads that spelling.
        query = {
            "shippper_account_numer": shipper_account_number,
            "order_number": order_number,
            "old_date": old_date,
            "language": language,
        }
        return self._request(
            "PATCH",
            endpoints.FORWARDING_ORDERS,
            payload=json_patch(operations),
            query=query,
            **kwargs,
        )

    def search_orders(self, *, criteria: str, **kwargs: Any) -> UPSResponse:
        return self._request(
            "GET", endpoints.FORWARDING_ORDERS, query={"criteria": criteria}, **kwargs
        )

    # --- shipments ---------------------------------------------------
    def create_shipment(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_SHIPMENTS, payload, **kwargs)

    def cancel_shipment(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._request(
            "DELETE", endpoints.FORWARDING_SHIPMENTS, payload=payload, **kwargs
        )

    def process_shipments(
        self,
        operations: Sequence[JsonObject],
        *,
        shipper_account_number: str,
        pickup_date: Optional[str] = None,
        request_manifest: Optional[bool] = None,
        manifest_format: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query: dict[str, Any] = {"shipper_account_number": shipper_account_number}
        if pickup_date:
            query["pickup_date"] = pickup_date
        if request_manifest is not None:
            query["request_manifest"] = bool_str(request_manifest)
        if manifest_format:
            query["manifest_format"] = manifest_format
        return self._request(
            "PATCH",
            endpoints.FORWARDING_SHIPMENTS,
            payload=json_patch(operations),
            query=query,
            **kwargs,
        )

    def shipment_details(
        self,
        *,
        shipment_id: str,
        request_type: str,
        **kwargs: Any,
    ) -> UPSResponse:
        return self._request(
            "GET",
            endpoints.FORWARDING_SHIPMENTS,
            query={"request_type": request_type, "shipment_id": shipment_id},
            **kwargs,
        )

    def freight_rates(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_SHIPMENT_RATES, payload, **kwargs)

    def milestones(
        self,
        *,
        business_id: Optional[str] = None,
        ups_file_number: Optional[str] = None,
        ups_office: Optional[str] = None,
        ups_shipment_number: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {
            "business_id": business_id,
            "ups_file_number": ups_file_number,
            "ups_office": ups_office,
            "ups_shipment_number": ups_shipment_number,
        }
        return self._request(
            "GET", endpoints.FORWARDING_SHIPMENT_MILESTONES, query=query, **kwargs
        )

    # --- quotes ------------------------------------------------------
    def create_quote(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_QUOTES, payload, **kwargs)

    def update_quote(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._request("PATCH", endpoints.FORWARDING_QUOTES, payload=payload, **kwargs)

    def search_quotes(
        self,
        *,
        request_type: str,
        quote_id: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {"request_type": request_type, "quote_id": quote_id}
        return self._request("GET", endpoints.FORWARDING_QUOTES, query=query, **kwargs)

    # --- documents ---------------------------------------------------
    def reprint_label(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_LABELS, payload, **kwargs)

    def create_manifest(self, payload: JsonObject, **kwargs: Any) -> UPSResponse:
        return self._post(endpoints.FORWARDING_MANIFEST, payload, **kwargs)

    # --- reference data ----------------------------------------------
    def cities(
        self,
        *,
        shipper_account_number: str,
        country: str,
        city: Optional[str] = None,
        postal: Optional[str] = None,
        criteria_operator: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {
            "shipper_account_number": shipper_account_number,
            "country": country,
            "city": city,
            "postal": postal,
            "criteria_operator": criteria_operator,
        }
        return self._request("GET", endpoints.FORWARDING_CITIES, query=query, **kwargs)

    def currencies(self, *, shipper_account_number: str, **kwargs: Any) -> UPSResponse:
        return self._request(
            "GET",
            endpoints.FORWARDING_CURRENCIES,
            query={"shipper_account_number": shipper_account_number},
            **kwargs,
        )

    def countries(self, *, shipper_account_number: str, **kwargs: Any) -> UPSResponse:
        return self._request(
            "GET",
            endpoints.FORWARDING_COUNTRIES,
            query={"shipper_account_number": shipper_account_number},
            **kwargs,
        )

    def airports(self, *, country_code: str, **kwargs: Any) -> UPSResponse:
        return self._request(
            "GET",
            endpoints.FORWARDING_AIRPORTS,
            query={"country_code": country_code},
            **kwargs,
        )

    def payment_types(
        self,
        *,
        shipper_account_number: str,
        code: Optional[str] = None,
        incoterm_code: Optional[str] = None,
        movement_type_code: Optional[str] = None,
        origin_country_code: Optional[str] = None,
        destination_country_code: Optional[str] = None,
        service_line: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {
            "shipper_account_number": shipper_account_number,
            "code": code,
            "incoterm_code": incoterm_code,
            "movement_type_code": movement_type_code,
            "origin_country_code": origin_country_code,
            "destination_country_code": destination_country_code,
            "service_line": service_line,
        }
        return self._request(
            "GET", endpoints.FORWARDING_PAYMENT_TYPES, query=query, **kwargs
        )

    def service_types(
        self,
        *,
        shipper_account_number: str,
        shipper_city: Optional[str] = None,
        shipper_state_code: Optional[str] = None,
        shipper_postal_code: Optional[str] = None,
        shipper_country_code: Optional[str] = None,
        consignee_city: Optional[str] = None,
        consignee_state_code: Optional[str] = None,
        consignee_postal_code: Optional[str] = None,
        consignee_country_code: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        query = {
            "shipper_account_number": shipper_account_number,
            "shipper_city": shipper_city,
            "shipper_state_code": shipper_state_code,
            "shipper_postal_code": shipper_postal_code,
            "shipper_country_code": shipper_country_code,
            "consignee_city": consignee_city,
            "consignee_state_code": consignee_state_code,
            "consignee_postal_code": consignee_postal_code,
            "consignee_country_code": consignee_country_code,
        }
        return self._request(
            "GET", endpoints.FORWARDING_SERVICE_TYPES, query=query, **kwargs
        )

    def accessorials(
        self,
        payload: JsonObject,
        *,
        account_number: Optional[str] = None,
        manifest_number: Optional[str] = None,
        manifest_format: Optional[str] = None,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        extra = {
            "account_number": account_number,
            "manifest_number": manifest_number,
            "manifest_format": manifest_format,
            "language": language,
        }
        headers = {k: v for k, v in extra.items() if v is not None}
        headers.update(kwargs.pop("headers", None) or {})
        return self._post(endpoints.FORWARDING_ACCESSORIALS, payload, headers=headers, **kwargs)

    # --- plumbing ----------------------------------------------------
    def _post(self, template: str, payload: Any, **kwargs: Any) -> UPSResponse:
        return self._request("POST", template, payload=payload, **kwargs)

    def _request(
        self,
        method: str,
        template: str,
        *,
        payload: Any = None,
        query: Optional[Mapping[str, Any]] = None,
        version: str = endpoints.FORWARDING_VERSION,
        business_guid: Optional[str] = None,
        client_id: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> UPSResponse:
        merged = forwarding_headers(
            business_guid=business_guid or self._business_guid,
            client_id=client_id or self._client_id,
        )
        if headers:
            merged.update(headers)
        return self._client.request(
            method,
            template.format(version=version),
            json_body=payload,
            query=query,
            headers=merged,
            **kwargs,
        )


__all__ = [
    "AddressesResource",
    "DangerousGoodsResource",
    "ForwardingResource",
    "OAuthResource",
    "PaperlessResource",
    "PickupsResource",
    "RatingResource",
    "ShippingResource",
    "TrackingResource",
    "TradeResource",
    "VisibilityResource",
]
