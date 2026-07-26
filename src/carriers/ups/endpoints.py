"""UPS endpoint paths and default API versions.

Every path here is transcribed from the Postman collections bundled in
``docs/postman/ups/``. Where UPS's own path contains a typo — notably
``/api/fowarding/`` for Forwarding — it is reproduced verbatim, because the
server routes on the misspelling.

Versions are the current defaults in UPS's published specs. Each client
method takes a ``version=`` keyword, so a UPS version bump is a call-site
override rather than a release of this package.
"""
from __future__ import annotations

# --- default API versions -------------------------------------------------
RATING_VERSION = "v2409"
SHIPPING_VERSION = "v2409"
PICKUP_VERSION = "v2409"
PICKUP_INFO_VERSION = "v1"
ADDRESS_VALIDATION_VERSION = "v2"
PAPERLESS_VERSION = "v2"
TIME_IN_TRANSIT_VERSION = "v1"
LABEL_RECOVERY_VERSION = "v1"
LANDED_COST_VERSION = "v1"
CUSTOMS_DETAIL_VERSION = "v2"
QUANTUM_VIEW_VERSION = "v2"
PRE_NOTIFICATION_VERSION = "v2"
DELIVERY_INTERCEPT_VERSION = "v2"
FORWARDING_VERSION = "v1"
TRACK_VERSION = "v1"

# --- OAuth ---------------------------------------------------------------
OAUTH_TOKEN = "/security/v1/oauth/token"
OAUTH_AUTHORIZE = "/security/v1/oauth/authorize"
OAUTH_REFRESH = "/security/v1/oauth/refresh"

# --- Tracking / Track Alert ----------------------------------------------
TRACK_DETAILS = "/api/track/{version}/details/{inquiry_number}"
TRACK_REFERENCE_DETAILS = "/api/track/{version}/reference/details/{reference_number}"
TRACK_ALERT_STANDARD = "/api/track/{version}/subscription/standard/package"
TRACK_ALERT_ENHANCED = "/api/track/{version}/subscription/enhanced/package"

# --- Rating / Time in Transit --------------------------------------------
RATING = "/api/rating/{version}/{request_option}"
TIME_IN_TRANSIT = "/api/shipments/{version}/transittimes"

# --- Shipping ------------------------------------------------------------
SHIP = "/api/shipments/{version}/ship"
VOID_SHIPMENT = "/api/shipments/{version}/void/cancel/{shipment_id}"
LABEL_RECOVERY = "/api/labels/{version}/recovery"

# --- Address Validation --------------------------------------------------
ADDRESS_VALIDATION = "/api/addressvalidation/{version}/{request_option}"

# --- Pickup --------------------------------------------------------------
PICKUP_RATE = "/api/shipments/{version}/pickup/{pickup_type}"
PICKUP_PENDING = "/api/shipments/{version}/pickup/{pickup_type}"
PICKUP_CANCEL = "/api/shipments/{version}/pickup/{cancel_by}"
PICKUP_CREATE = "/api/pickupcreation/{version}/pickup"
PICKUP_POLITICAL_DIVISIONS = "/api/pickup/{version}/countries/{country_code}"
PICKUP_SERVICE_CENTERS = "/api/pickup/{version}/servicecenterlocations"

# --- Paperless Documents -------------------------------------------------
PAPERLESS_UPLOAD = "/api/paperlessdocuments/{version}/upload"
PAPERLESS_PUSH_IMAGE = "/api/paperlessdocuments/{version}/image"
# The literal path segments are part of UPS's contract; the real identifiers
# travel in the DocumentId and ShipperNumber headers.
PAPERLESS_DELETE = "/api/paperlessdocuments/{version}/DocumentId/ShipperNumber"

# --- International trade -------------------------------------------------
LANDED_COST_QUOTES = "/api/landedcost/{version}/quotes"
CUSTOMS_DETAIL = "/api/trade/compliance/{version}/content/fields/customs-detail"
EXPORT_ASSURE_COMPLIANCE = "/api/brokerage/v1/importexport/exportassure"
EXPORT_ASSURE_INTERACTIVE = "/api/export-assure/v1/interactive"

# --- Visibility and delivery change --------------------------------------
QUANTUM_VIEW_EVENTS = "/api/quantumview/{version}/events"
DELIVERY_INTERCEPT_CHARGES = "/api/deliverychange/{version}/charges/{tracking_number}"
DELIVERY_DEFENSE_SCORE = "/api/deliverydefense/external/v1.0/address/score"

# --- Dangerous goods -----------------------------------------------------
PRE_NOTIFICATION = "/api/dangerousgoods/{version}/prenotification"

# --- Forwarding (UPS spells the path "fowarding") ------------------------
FORWARDING_ORDERS = "/api/fowarding/{version}/orders"
FORWARDING_SHIPMENTS = "/api/fowarding/{version}/shipments"
FORWARDING_SHIPMENT_RATES = "/api/fowarding/{version}/shipments/rates"
FORWARDING_SHIPMENT_MILESTONES = "/api/fowarding/{version}/shipments/milestones"
FORWARDING_QUOTES = "/api/fowarding/{version}/quotes"
FORWARDING_LABELS = "/api/fowarding/{version}/documents/labels"
FORWARDING_MANIFEST = "/api/fowarding/{version}/documents/manifest"
FORWARDING_CITIES = "/api/fowarding/{version}/info/cities"
FORWARDING_CURRENCIES = "/api/fowarding/{version}/info/currencies"
FORWARDING_COUNTRIES = "/api/fowarding/{version}/info/countries"
FORWARDING_AIRPORTS = "/api/fowarding/{version}/info/airports"
FORWARDING_PAYMENT_TYPES = "/api/fowarding/{version}/info/payment-types"
FORWARDING_SERVICE_TYPES = "/api/fowarding/{version}/info/service-types"
FORWARDING_ACCESSORIALS = "/api/fowarding/{version}/info/accessorials"
