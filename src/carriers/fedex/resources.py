"""Namespaced FedEx API surfaces: ``client.documents.upload_etd(...)``.

The notebook that started this restructure reached for
``fx.documents.upload_etd(local_file, pro)`` and got an ``AttributeError``,
because the SDK only had a flat ``upload_commercial_invoice``. That instinct
was right — it mirrors how ``ab`` is organised — so this is the shape the
FedEx adapter now has.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional, Sequence, Union
from urllib.parse import quote

from .._core.multipart import encode_multipart_form_data
from .._core.resources import Resource
from . import endpoints
from .documents import (
    COMMERCIAL_INVOICE,
    POSTSHIPMENT_WORKFLOW,
    PRESHIPMENT_WORKFLOW,
    FileSource,
    attach_pre_shipment_documents,
    build_etd_document,
    extract_uploaded_document_id,
    read_upload_attachment,
    uploaded_document_reference,
)
from .models import FedExResponse

JsonObject = Mapping[str, Any]


class ShipResource(Resource):
    """Ship API: shipments, cancellations, tags and async results."""

    def create(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.SHIP_CREATE, payload, **kwargs)

    def cancel(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Cancel a shipment.

        The Ship API routes this as PUT; the 0.1 SDK sent POST.
        """
        return self._client.put(endpoints.SHIP_CANCEL, payload, **kwargs)

    def validate(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Validate a shipment without buying a label."""
        return self._client.post(endpoints.SHIP_VALIDATE, payload, **kwargs)

    def results(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Retrieve the result of an asynchronous shipment request."""
        return self._client.post(endpoints.SHIP_RESULTS, payload, **kwargs)

    def create_tag(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Dispatch a courier to collect a package (FedEx Tag)."""
        return self._client.post(endpoints.SHIP_TAG_CREATE, payload, **kwargs)

    def cancel_tag(
        self, shipment_id: str, payload: JsonObject, **kwargs: Any
    ) -> FedExResponse:
        path = endpoints.SHIP_TAG_CANCEL.format(shipment_id=quote(shipment_id, safe=""))
        return self._client.put(path, payload, **kwargs)

    def end_of_day_close(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Ground end-of-day close. See ``endpoints.UNVERIFIED``."""
        return self._client.post(endpoints.GROUND_END_OF_DAY_CLOSE, payload, **kwargs)


class RateResource(Resource):
    """Rate API."""

    def quotes(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.RATE_QUOTES, payload, **kwargs)

    def freight_quotes(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """LTL freight rates. See ``endpoints.UNVERIFIED``."""
        return self._client.post(endpoints.RATE_FREIGHT_QUOTES, payload, **kwargs)


class TrackResource(Resource):
    """Track API."""

    def by_tracking_numbers(
        self,
        tracking_numbers: Sequence[str],
        *,
        include_detailed_scans: bool = False,
        **kwargs: Any,
    ) -> FedExResponse:
        payload = {
            "includeDetailedScans": include_detailed_scans,
            "trackingInfo": [
                {"trackingNumberInfo": {"trackingNumber": tracking_number}}
                for tracking_number in tracking_numbers
            ],
        }
        return self._client.post(endpoints.TRACK_BY_NUMBER, payload, **kwargs)

    def by_payload(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Track with a hand-built payload (multi-piece, date ranges, …)."""
        return self._client.post(endpoints.TRACK_BY_NUMBER, payload, **kwargs)

    # The rest of the Track family — see ``endpoints.UNVERIFIED``.
    def by_reference(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.TRACK_BY_REFERENCE, payload, **kwargs)

    def by_tcn(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Track by Transportation Control Number (government shipments)."""
        return self._client.post(endpoints.TRACK_BY_TCN, payload, **kwargs)

    def associated_shipments(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.TRACK_ASSOCIATED, payload, **kwargs)

    def notifications(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Register tracking event notifications."""
        return self._client.post(endpoints.TRACK_NOTIFICATIONS, payload, **kwargs)

    def documents(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Signature proof of delivery and other tracking documents."""
        return self._client.post(endpoints.TRACK_DOCUMENTS, payload, **kwargs)


class AddressesResource(Resource):
    """Address Validation API."""

    def resolve(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.ADDRESS_RESOLVE, payload, **kwargs)

    def validate_postal(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Postal code validation. See ``endpoints.UNVERIFIED``."""
        return self._client.post(endpoints.POSTAL_VALIDATE, payload, **kwargs)


class LocationsResource(Resource):
    """Location API."""

    def search(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.LOCATION_SEARCH, payload, **kwargs)


class PickupsResource(Resource):
    """Pickup API."""

    def availability(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.PICKUP_AVAILABILITY, payload, **kwargs)

    def create(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.PICKUP_CREATE, payload, **kwargs)

    def cancel(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.PICKUP_CANCEL, payload, **kwargs)


class AvailabilityResource(Resource):
    """Service Availability API. See ``endpoints.UNVERIFIED``."""

    def service_options(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.SERVICE_OPTIONS, payload, **kwargs)

    def transit_times(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        return self._client.post(endpoints.SERVICE_TRANSIT_TIMES, payload, **kwargs)


class DocumentsResource(Resource):
    """Trade Documents Upload API — the ETD surface.

    Pre-shipment uploads first and references the returned ``docId`` on the
    shipment payload (:meth:`attach_to_shipment`). Post-shipment uploads after
    the label exists, and requires the tracking number and ship date. Choosing
    the wrong workflow is the single most common ETD mistake, so the two have
    separate methods rather than a flag.
    """

    def upload_etd(
        self,
        attachment: FileSource,
        *,
        origin_country_code: str,
        destination_country_code: str,
        document_type: str = COMMERCIAL_INVOICE,
        workflow_name: str = PRESHIPMENT_WORKFLOW,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        carrier_code: Optional[str] = None,
        form_code: Optional[str] = None,
        tracking_number: Optional[str] = None,
        shipment_date: Optional[str] = None,
        origin_location_code: Optional[str] = None,
        destination_location_code: Optional[str] = None,
        extra_meta: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> FedExResponse:
        """Upload one electronic trade document."""

        part = read_upload_attachment(attachment, filename=filename, content_type=content_type)
        document = build_etd_document(
            filename=part.filename,
            content_type=part.content_type,
            origin_country_code=origin_country_code,
            destination_country_code=destination_country_code,
            ship_document_type=document_type,
            workflow_name=workflow_name,
            carrier_code=carrier_code,
            form_code=form_code,
            tracking_number=tracking_number,
            shipment_date=shipment_date,
            origin_location_code=origin_location_code,
            destination_location_code=destination_location_code,
            extra_meta=extra_meta,
        )
        return self.upload_document(
            document,
            part.content,
            filename=part.filename,
            content_type=part.content_type,
            **kwargs,
        )

    def upload_pre_shipment(
        self,
        attachment: FileSource,
        *,
        origin_country_code: str,
        destination_country_code: str,
        **kwargs: Any,
    ) -> FedExResponse:
        """Upload before booking; attach the returned docId to the shipment."""

        return self.upload_etd(
            attachment,
            origin_country_code=origin_country_code,
            destination_country_code=destination_country_code,
            workflow_name=PRESHIPMENT_WORKFLOW,
            **kwargs,
        )

    def upload_post_shipment(
        self,
        attachment: FileSource,
        *,
        origin_country_code: str,
        destination_country_code: str,
        tracking_number: str,
        shipment_date: str,
        carrier_code: str = "FDXE",
        **kwargs: Any,
    ) -> FedExResponse:
        """Upload against a label that already exists.

        This is the shape any integration that books through a third party
        needs: the label was bought elsewhere, so the document is lodged after
        the fact and must carry ``trackingNumber`` and ``shipmentDate``.
        """

        return self.upload_etd(
            attachment,
            origin_country_code=origin_country_code,
            destination_country_code=destination_country_code,
            tracking_number=tracking_number,
            shipment_date=shipment_date,
            carrier_code=carrier_code,
            workflow_name=POSTSHIPMENT_WORKFLOW,
            **kwargs,
        )

    def upload_document(
        self,
        document: JsonObject,
        attachment: FileSource,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        path: str = endpoints.ETD_UPLOAD,
        **kwargs: Any,
    ) -> FedExResponse:
        """Upload with a hand-built document metadata block."""

        part = read_upload_attachment(
            attachment,
            filename=filename,
            content_type=content_type or str(document.get("contentType", "")) or None,
        )
        document_payload = json.dumps(dict(document), separators=(",", ":"))
        body, multipart_content_type = encode_multipart_form_data(
            fields=[("document", document_payload, "application/json")],
            files=[("attachment", part.filename, part.content, part.content_type)],
        )
        return self._client.request(
            "POST",
            f"{self.config.resolved_document_base_url}{path}",
            headers={"Content-Type": multipart_content_type},
            body=body,
            **kwargs,
        )

    def upload_images(
        self,
        document: JsonObject,
        attachment: FileSource,
        **kwargs: Any,
    ) -> FedExResponse:
        """Upload a letterhead or signature image for label printing."""

        return self.upload_document(
            document, attachment, path=endpoints.LHS_IMAGE_UPLOAD, **kwargs
        )

    def upload_encoded_documents(self, payload: JsonObject, **kwargs: Any) -> FedExResponse:
        """Upload several base64-encoded documents in one JSON request."""

        return self._client.post(
            f"{self.config.resolved_document_base_url}{endpoints.ETD_ENCODED_MULTIUPLOAD}",
            payload,
            **kwargs,
        )

    def document_id(self, response: Union[FedExResponse, Any]) -> Optional[str]:
        data = response.data if isinstance(response, FedExResponse) else response
        return extract_uploaded_document_id(data)

    def reference(
        self,
        document_id: str,
        *,
        document_type: str = COMMERCIAL_INVOICE,
        document_reference: Optional[str] = None,
        description: Optional[str] = "Commercial Invoice",
    ) -> dict:
        """Build the ``attachedDocuments`` entry for a shipment payload."""

        return uploaded_document_reference(
            document_id=document_id,
            document_type=document_type,
            document_reference=document_reference,
            description=description,
        )

    def attach_to_shipment(
        self,
        shipment_payload: JsonObject,
        documents: Sequence[Mapping[str, Any]],
        *,
        requested_document_types: Optional[Sequence[str]] = None,
    ) -> dict:
        return attach_pre_shipment_documents(
            shipment_payload,
            list(documents),
            requested_document_types=list(requested_document_types)
            if requested_document_types is not None
            else None,
        )


__all__ = [
    "AddressesResource",
    "AvailabilityResource",
    "DocumentsResource",
    "LocationsResource",
    "PickupsResource",
    "RateResource",
    "ShipResource",
    "TrackResource",
]
