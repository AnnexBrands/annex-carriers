import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

# The clients log every failed request, which is the point in production and
# noise in a suite that asserts on failures. Tests that care about logging
# attach their own handler.
logging.getLogger("carriers").addHandler(logging.NullHandler())
logging.getLogger("carriers").propagate = False
