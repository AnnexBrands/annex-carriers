from __future__ import annotations

from dataclasses import dataclass

from .._core.models import AccessToken, CarrierResponse


@dataclass(frozen=True)
class FedExResponse(CarrierResponse):
    """A parsed FedEx response. Identical to the base; named for clarity."""


__all__ = ["AccessToken", "FedExResponse"]
