from __future__ import annotations

from dataclasses import dataclass

from .._core.models import AccessToken, CarrierResponse


@dataclass(frozen=True)
class UPSResponse(CarrierResponse):
    """A parsed UPS response. Identical to the base; named for clarity."""


__all__ = ["AccessToken", "UPSResponse"]
