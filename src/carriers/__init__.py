"""Annex carrier SDKs: one repository, one shared core, one adapter per carrier.

Layer 0 — ``carriers._core``  transport, retry, token lifecycle, error base,
                             config resolution. Internal; no carrier knowledge.
Layer 1 — ``carriers.ups``    UPS OAuth, versioned URL map, payload builders.
          ``carriers.fedex``  FedEx OAuth, URL map, ETD workflows.

Adapters never import each other, and never import anything above them. A
carrier package that learns what a job id is has taken on someone else's
concern.

    from carriers.ups import UPSClient
    from carriers.fedex import FedExClient

The shared error base makes cross-carrier handling possible without either
adapter knowing the other exists::

    from carriers import CarrierRateLimitError
"""
from __future__ import annotations

from ._core.errors import (
    CarrierAPIError,
    CarrierAuthenticationError,
    CarrierError,
    CarrierRateLimitError,
    CarrierTransportError,
    CarrierValidationError,
)
from ._core.models import AccessToken, CarrierResponse
from ._core.retry import RetryPolicy
from ._core.transport import HttpResponse, Transport, UrlLibTransport

__version__ = "0.2.0"

__all__ = [
    "AccessToken",
    "CarrierAPIError",
    "CarrierAuthenticationError",
    "CarrierError",
    "CarrierRateLimitError",
    "CarrierResponse",
    "CarrierTransportError",
    "CarrierValidationError",
    "HttpResponse",
    "RetryPolicy",
    "Transport",
    "UrlLibTransport",
    "__version__",
]
