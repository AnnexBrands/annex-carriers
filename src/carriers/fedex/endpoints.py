"""FedEx endpoint paths.

Provenance matters here, because unlike UPS we do not hold a Postman export
for every family. Each block below is tagged:

``[spec]``   transcribed from an OpenAPI document in ``docs/specs/fedex/``.
``[live]``   already exercised against FedEx by the 0.1 SDK.
``[portal]`` taken from FedEx's published API catalog but not verified here —
             confirm the path and method against your FedEx developer portal
             account before relying on it in production.

Every client method takes the path from this module, so correcting one is a
single-line change with no call-site churn.
"""
from __future__ import annotations

# --- OAuth [live] --------------------------------------------------------
OAUTH_TOKEN = "/oauth/token"

# --- Ship [spec: docs/specs/fedex/ship.json] -----------------------------
SHIP_CREATE = "/ship/v1/shipments"
# NOTE: PUT, not POST. The 0.1 SDK sent POST here, which the Ship API does
# not route.
SHIP_CANCEL = "/ship/v1/shipments/cancel"
SHIP_RESULTS = "/ship/v1/shipments/results"
# NOTE: the validate route is under /packages/, not /ship/v1/shipments/validate.
SHIP_VALIDATE = "/ship/v1/shipments/packages/validate"
SHIP_TAG_CREATE = "/ship/v1/shipments/tag"
SHIP_TAG_CANCEL = "/ship/v1/shipments/tag/cancel/{shipment_id}"

# --- Trade Documents Upload [spec: docs/specs/fedex/upload-documents.json]
ETD_UPLOAD = "/documents/v1/etds/upload"
ETD_MULTIUPLOAD = "/documents/v1/etds/multiupload"
ETD_ENCODED_MULTIUPLOAD = "/documents/v1/etds/encodedmultiupload"
LHS_IMAGE_UPLOAD = "/documents/v1/lhsimages/upload"

# --- Rate [live] ---------------------------------------------------------
RATE_QUOTES = "/rate/v1/rates/quotes"

# --- Track [live] --------------------------------------------------------
TRACK_BY_NUMBER = "/track/v1/trackingnumbers"

# --- Address, Location, Pickup [live] ------------------------------------
ADDRESS_RESOLVE = "/address/v1/addresses/resolve"
LOCATION_SEARCH = "/location/v1/locations"
PICKUP_CREATE = "/pickup/v1/pickups"
PICKUP_CANCEL = "/pickup/v1/pickups/cancel"
PICKUP_AVAILABILITY = "/pickup/v1/pickups/availabilities"

# --- [portal] ------------------------------------------------------------
# Confirm these against your FedEx developer portal before production use.
TRACK_BY_REFERENCE = "/track/v1/referencenumbers"
TRACK_BY_TCN = "/track/v1/tcn"
TRACK_ASSOCIATED = "/track/v1/associatedshipment"
TRACK_NOTIFICATIONS = "/track/v1/notifications"
TRACK_DOCUMENTS = "/track/v1/trackingdocuments"
RATE_FREIGHT_QUOTES = "/rate/v1/freight/rates/quotes"
POSTAL_VALIDATE = "/country/v1/postal/validate"
SERVICE_OPTIONS = "/availability/v1/packageandserviceoptions"
SERVICE_TRANSIT_TIMES = "/availability/v1/transittimes"
GROUND_END_OF_DAY_CLOSE = "/ship/v1/endofday/close"

#: Families whose paths have not been verified against a spec or a live call.
UNVERIFIED = frozenset(
    {
        TRACK_BY_REFERENCE,
        TRACK_BY_TCN,
        TRACK_ASSOCIATED,
        TRACK_NOTIFICATIONS,
        TRACK_DOCUMENTS,
        RATE_FREIGHT_QUOTES,
        POSTAL_VALIDATE,
        SERVICE_OPTIONS,
        SERVICE_TRANSIT_TIMES,
        GROUND_END_OF_DAY_CLOSE,
    }
)
