"""Compatibility shim for the pre-merge ``ups_sdk`` package name.

``ups-api-sdk`` and ``fedex-api-sdk`` were merged into ``annex-carriers`` so
the transport, retry and error layers stop being maintained twice. Import
:mod:`carriers.ups` instead; this module will be removed once nothing
references it.
"""
from __future__ import annotations

import warnings

from carriers.ups import *  # noqa: F401,F403
from carriers.ups import __all__ as _all
from carriers import __version__

warnings.warn(
    "ups_sdk has moved to carriers.ups; update your imports.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_all)
