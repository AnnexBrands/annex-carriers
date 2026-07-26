"""Paperless Documents API payload builders and response parsing.

UPS paperless trade documents are uploaded to Forms History as base64 JSON
(``POST /api/paperlessdocuments/{version}/upload``), then either referenced on
a new shipment via ``ShipmentServiceOptions.InternationalForms`` (FormType
``07``, user-created forms) or pushed to the image repository for an existing
shipment (``POST /api/paperlessdocuments/{version}/image``). The shipper
account must have "Upload Forms Created Offline" enabled.
"""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Mapping, MutableMapping, Optional, Sequence, Union

FileSource = Union[str, Path, bytes, IO[bytes]]

# UserCreatedFormDocumentType codes.
AUTHORIZATION_FORM = "001"
COMMERCIAL_INVOICE = "002"
CERTIFICATE_OF_ORIGIN = "003"
EXPORT_ACCOMPANYING_DOCUMENT = "004"
EXPORT_LICENSE = "005"
IMPORT_PERMIT = "006"
ONE_TIME_USMCA = "007"
OTHER_DOCUMENT = "008"
POWER_OF_ATTORNEY = "009"
PACKING_LIST = "010"
SED_DOCUMENT = "011"
SHIPPERS_LETTER_OF_INSTRUCTION = "012"
DECLARATION = "013"

# InternationalForms FormType for pre-uploaded (user-created) documents.
USER_CREATED_FORM = "07"


@dataclass(frozen=True)
class DocumentFile:
    filename: str
    content: bytes
    file_format: str


def read_document_file(
    file: FileSource,
    *,
    filename: Optional[str] = None,
    file_format: Optional[str] = None,
) -> DocumentFile:
    """Resolve a path, bytes, or file-like object into an upload-ready file.

    ``file_format`` is UPS's ``UserCreatedFormFileFormat`` (the bare extension,
    e.g. ``pdf``); it defaults to the filename's extension.
    """

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

    resolved_format = (file_format or Path(resolved_filename).suffix.lstrip(".")).lower()
    if not resolved_format:
        raise ValueError("file_format= is required when the filename has no extension")
    return DocumentFile(
        filename=resolved_filename,
        content=content,
        file_format=resolved_format,
    )


def build_user_created_form(
    *,
    filename: str,
    file_format: str,
    document_type: str,
    content: bytes,
) -> dict[str, str]:
    """Build one ``UserCreatedForm`` entry with base64-encoded content."""

    return {
        "UserCreatedFormFileName": filename,
        "UserCreatedFormFileFormat": file_format,
        "UserCreatedFormDocumentType": document_type,
        "UserCreatedFormFile": base64.b64encode(content).decode("ascii"),
    }


def build_upload_request(
    shipper_number: str,
    forms: Sequence[Mapping[str, Any]],
    *,
    customer_context: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /api/paperlessdocuments/{version}/upload`` payload."""

    if not forms:
        raise ValueError("forms must contain at least one UserCreatedForm entry")
    request: dict[str, Any] = {}
    if customer_context:
        request["TransactionReference"] = {"CustomerContext": customer_context}
    return {
        "UploadRequest": {
            "Request": request,
            "ShipperNumber": shipper_number,
            "UserCreatedForm": [dict(form) for form in forms],
        }
    }


def build_push_to_repository_request(
    shipper_number: str,
    *,
    document_ids: Sequence[str],
    shipment_identifier: str,
    shipment_date_and_time: str,
    shipment_type: str = "1",
    tracking_number: Optional[str] = None,
    customer_context: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble a ``POST /api/paperlessdocuments/{version}/image`` payload.

    ``shipment_date_and_time`` uses UPS's ``yyyy-MM-dd-HH.mm.ss`` format;
    ``shipment_type`` ``1`` is a small-package shipment.
    """

    request: dict[str, Any] = {}
    if customer_context:
        request["TransactionReference"] = {"CustomerContext": customer_context}
    payload: dict[str, Any] = {
        "PushToImageRepositoryRequest": {
            "Request": request,
            "ShipperNumber": shipper_number,
            "FormsHistoryDocumentID": {"DocumentID": list(document_ids)},
            "ShipmentIdentifier": shipment_identifier,
            "ShipmentDateAndTime": shipment_date_and_time,
            "ShipmentType": shipment_type,
        }
    }
    if tracking_number:
        payload["PushToImageRepositoryRequest"]["TrackingNumber"] = tracking_number
    return payload


def extract_document_ids(response_data: Any) -> list[str]:
    """Return uploaded DocumentIDs from an ``UploadResponse``.

    Handles both the v2 array shape and v1's single-object collapse.
    """

    if not isinstance(response_data, Mapping):
        return []
    containers = (response_data.get("UploadResponse") or {}).get("FormsHistoryDocumentID")
    if containers is None:
        return []
    if isinstance(containers, Mapping):
        containers = [containers]
    ids: list[str] = []
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        document_id = container.get("DocumentID")
        if isinstance(document_id, str):
            ids.append(document_id)
        elif isinstance(document_id, Sequence):
            ids.extend(str(value) for value in document_id)
    return ids


def attach_paperless_documents(
    ship_payload: Mapping[str, Any],
    document_ids: Sequence[str],
) -> dict[str, Any]:
    """Return a shipment payload with uploaded DocumentIDs attached.

    Adds ``InternationalForms`` with FormType ``07`` (user-created forms) under
    ``Shipment.ShipmentServiceOptions``, merging with any forms already there.
    """

    if not document_ids:
        raise ValueError("document_ids must contain at least one uploaded DocumentID")

    payload = copy.deepcopy(dict(ship_payload))
    shipment_request = _ensure_dict(payload, "ShipmentRequest")
    shipment = _ensure_dict(shipment_request, "Shipment")
    service_options = _ensure_dict(shipment, "ShipmentServiceOptions")
    forms = _ensure_dict(service_options, "InternationalForms")

    form_type = forms.get("FormType")
    if form_type is None:
        forms["FormType"] = USER_CREATED_FORM
    elif isinstance(form_type, str) and form_type != USER_CREATED_FORM:
        forms["FormType"] = [form_type, USER_CREATED_FORM]
    elif isinstance(form_type, list) and USER_CREATED_FORM not in form_type:
        form_type.append(USER_CREATED_FORM)

    user_created = _ensure_dict(forms, "UserCreatedForm")
    existing = user_created.get("DocumentID") or []
    if isinstance(existing, str):
        existing = [existing]
    user_created["DocumentID"] = list(existing) + [
        document_id for document_id in document_ids if document_id not in existing
    ]
    return payload


def _ensure_dict(parent: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    value = parent.get(key)
    if value is None:
        value = {}
        parent[key] = value
    if not isinstance(value, MutableMapping):
        raise ValueError(f"{key} must be an object")
    return value
