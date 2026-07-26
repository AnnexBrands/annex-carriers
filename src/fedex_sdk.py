"""Compatibility shim for the pre-merge ``fedex_sdk`` package name.

``fedex-api-sdk`` and ``ups-api-sdk`` were merged into ``annex-carriers`` so
the transport, retry and error layers stop being maintained twice. Import
:mod:`carriers.fedex` instead; this module will be removed once nothing
references it.
"""
from __future__ import annotations

import warnings

from carriers.fedex import *  # noqa: F401,F403
from carriers.fedex import __all__ as _all
from carriers import __version__

warnings.warn(
    "fedex_sdk has moved to carriers.fedex; update your imports.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_all)
