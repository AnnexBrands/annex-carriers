"""Packaging contract for the forwardair adapter (feature 011, US4).

Two promises this package makes, both easy to break by accident:

1. ``carriers.forwardair`` is usable with only ``annex-carriers[forwardair]``
   installed — no abtool, no db, no pandas.
2. The base package keeps ``dependencies = []``. The README says "no runtime
   dependencies" and UPS/FedEx consumers rely on it, so pdfminer must stay
   behind the opt-in extra and must never be reachable from ``import carriers``.

The static checks below run in the normal suite. The full isolation proof needs
a clean virtualenv and is too slow for every run, so it is marked ``slow``:

    pytest tests/forwardair -m slow
"""
from __future__ import annotations

import ast
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "carriers"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level:
            names.update(a.name for a in node.names)
    return names


# ---- the base package stays clean ----------------------------------------

def test_package_root_does_not_import_forwardair():
    """``import carriers`` must not drag in pdfminer. A consumer without the
    extra installed would get an ImportError on an unrelated import."""
    text = (SRC / "__init__.py").read_text()
    assert "forwardair" not in text


def test_package_root_imports_only_internal_core():
    modules = _imported_modules(SRC / "__init__.py")
    assert all(m.startswith("_core") or m.startswith("__future__") for m in modules), modules


def test_base_package_declares_no_runtime_dependencies():
    text = (REPO / "pyproject.toml").read_text()
    assert "dependencies = []" in text


def test_pdfminer_is_only_ever_an_extra():
    text = (REPO / "pyproject.toml").read_text()
    assert 'forwardair = ["pdfminer.six>=20221105"]' in text
    # It must not also appear in the base dependency list.
    base = text.split("[project.optional-dependencies]")[0]
    assert "pdfminer" not in base


# ---- the adapter stays domain-free ---------------------------------------

@pytest.mark.parametrize("module", ["__init__.py", "models.py", "parser.py"])
def test_forwardair_imports_nothing_from_the_caller_domain(module):
    """An adapter that learns what an ABConnect job id is has taken on someone
    else's concern (see carriers/__init__.py)."""
    modules = _imported_modules(SRC / "forwardair" / module)
    forbidden = {"abtool", "db", "pandas", "ab", "M365"}
    assert not (modules & forbidden), modules


def test_forwardair_does_not_import_other_adapters():
    for module in ("__init__.py", "models.py", "parser.py"):
        modules = _imported_modules(SRC / "forwardair" / module)
        assert not any(m.startswith(("ups", "fedex")) for m in modules)


def test_forwardair_exposes_no_client_class():
    """Forward Air's remittance channel is email attachments, not an API. A
    client here would be fiction."""
    from carriers import forwardair

    assert not [n for n in forwardair.__all__ if n.endswith("Client")]


def test_no_annex_billing_policy_leaked_into_the_package():
    """The 5% markup on CL*/Fuel Surcharge, the CSV shape, and the stored
    procedures are Annex policy and belong in abtool."""
    for module in ("__init__.py", "models.py", "parser.py"):
        text = (SRC / "forwardair" / module).read_text()
        for token in ("1.05", "Fuel Surcharge", "InsertForwardAir", "fwd"):
            assert token not in text, f"{module} mentions {token!r}"


# ---- full isolation proof (slow) -----------------------------------------

@pytest.mark.slow
def test_parses_in_a_clean_venv_without_abtool(tmp_path):
    """SC-005: a Forward Air PDF parses where abtool is not installed."""
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = env_dir / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", f"{REPO}[forwardair]"],
        check=True, capture_output=True,
    )
    probe = (
        "import importlib.util, sys\n"
        "from carriers.forwardair import parse_file, InvoiceParser, Invoice\n"
        "assert importlib.util.find_spec('abtool') is None, 'abtool leaked in'\n"
        "assert importlib.util.find_spec('pdfminer') is not None\n"
        "print('ok')\n"
    )
    out = subprocess.run([str(py), "-c", probe], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout


@pytest.mark.slow
def test_base_install_pulls_no_third_party_packages(tmp_path):
    """SC-006: installing without the extra brings in nothing but the package."""
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = env_dir / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", str(REPO)], check=True, capture_output=True
    )
    probe = (
        "import importlib.util\n"
        "import carriers\n"
        "assert importlib.util.find_spec('pdfminer') is None, 'pdfminer came along'\n"
        "print(carriers.__version__)\n"
    )
    out = subprocess.run([str(py), "-c", probe], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


if __name__ == "__main__":  # pragma: no cover — manual isolation check
    sys.exit(pytest.main([__file__, "-m", "slow", "-v"]))
