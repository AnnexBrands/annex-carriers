from __future__ import annotations

import copy
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Mapping, MutableMapping, Optional, Union

FileSource = Union[str, Path, bytes, IO[bytes]]

PRESHIPMENT_WORKFLOW = "ETDPreshipment"
POSTSHIPMENT_WORKFLOW = "ETDPostshipment"
COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
ELECTRONIC_TRADE_DOCUMENTS = "ELECTRONIC_TRADE_DOCUMENTS"


@dataclass(frozen=True)
class UploadAttachment:
    filename: str
    content: bytes
    content_type: str


def read_upload_attachment(
    file: FileSource,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> UploadAttachment:
    """Resolve a path, bytes, or file-like object into a multipart file part."""

    if isinstance(file, (str, Path)):
        path = Path(file)
        resolved_filename = filename or path.name
        content = path.read_bytes()
    else:
        if not filename:
            raise ValueError("filename= is required when uploading bytes or a file-like object")
        resolved_filename = filename
        if isinstance(file, bytes):
            content = file
        else:
            content = file.read()

    resolved_content_type = (
        content_type
        or mimetypes.guess_type(resolved_filename)[0]
        or "application/octet-stream"
    )
    return UploadAttachment(
        filename=resolved_filename,
        content=content,
        content_type=resolved_content_type,
    )


def build_etd_document(
    *,
    filename: str,
    content_type: str,
    origin_country_code: str,
    destination_country_code: str,
    ship_document_type: str = COMMERCIAL_INVOICE,
    workflow_name: str = PRESHIPMENT_WORKFLOW,
    carrier_code: Optional[str] = None,
    form_code: Optional[str] = None,
    tracking_number: Optional[str] = None,
    shipment_date: Optional[str] = None,
    origin_location_code: Optional[str] = None,
    destination_location_code: Optional[str] = None,
    extra_meta: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the JSON metadata part FedEx expects for ETD upload."""

    meta: dict[str, Any] = {
        "shipDocumentType": ship_document_type,
        "originCountryCode": origin_country_code,
        "destinationCountryCode": destination_country_code,
    }
    optional_meta = {
        "formCode": form_code,
        "trackingNumber": tracking_number,
        "shipmentDate": shipment_date,
        "originLocationCode": origin_location_code,
        "destinationLocationCode": destination_location_code,
    }
    meta.update({key: value for key, value in optional_meta.items() if value is not None})
    if extra_meta:
        meta.update(extra_meta)

    document: dict[str, Any] = {
        "workflowName": workflow_name,
        "name": filename,
        "contentType": content_type,
        "meta": meta,
    }
    if carrier_code:
        document["carrierCode"] = carrier_code
    return document


def uploaded_document_reference(
    *,
    document_id: str,
    document_type: str = COMMERCIAL_INVOICE,
    document_reference: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, str]:
    """Build a Ship API `attachedDocuments` entry from an upload docId."""

    reference = {
        "documentType": document_type,
        "documentId": document_id,
    }
    if document_reference is not None:
        reference["documentReference"] = document_reference
    if description is not None:
        reference["description"] = description
    return reference


def extract_uploaded_document_id(response_data: Any) -> Optional[str]:
    """Return the upload docId from common FedEx ETD upload response shapes."""

    if not isinstance(response_data, Mapping):
        return None
    output = response_data.get("output")
    if isinstance(output, Mapping):
        meta = output.get("meta")
        if isinstance(meta, Mapping) and meta.get("docId"):
            return str(meta["docId"])
    meta = response_data.get("meta")
    if isinstance(meta, Mapping) and meta.get("docId"):
        return str(meta["docId"])
    return None


def attach_pre_shipment_documents(
    shipment_payload: Mapping[str, Any],
    documents: list[Mapping[str, Any]],
    *,
    requested_document_types: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Return a shipment payload with pre-uploaded ETD document references attached."""

    if not documents:
        raise ValueError("documents must contain at least one uploaded document reference")

    payload = copy.deepcopy(dict(shipment_payload))
    requested_shipment = _ensure_dict(payload, "requestedShipment")
    shipment_services = _ensure_dict(requested_shipment, "shipmentSpecialServices")
    special_service_types = shipment_services.setdefault("specialServiceTypes", [])
    if ELECTRONIC_TRADE_DOCUMENTS not in special_service_types:
        special_service_types.append(ELECTRONIC_TRADE_DOCUMENTS)

    etd_detail = _ensure_dict(shipment_services, "etdDetail")
    etd_detail["attachedDocuments"] = [dict(document) for document in documents]
    if requested_document_types is not None:
        etd_detail["requestedDocumentTypes"] = list(requested_document_types)
    return payload


def _ensure_dict(parent: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    value = parent.get(key)
    if value is None:
        value = {}
        parent[key] = value
    if not isinstance(value, MutableMapping):
        raise ValueError(f"{key} must be an object")
    return value
