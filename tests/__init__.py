"""Test package setup shared by pytest and ``unittest discover``.

``conftest.py`` only runs under pytest, so the import path and log
suppression live here too — the suite must pass under either runner.
"""
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The clients log every failed request, which is the point in production and
# noise in a suite that asserts on failures. Tests that care about logging
# attach their own handler to their own logger.
_carriers_logger = logging.getLogger("carriers")
_carriers_logger.addHandler(logging.NullHandler())
_carriers_logger.propagate = False
