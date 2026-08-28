"""Forward Air remittance invoice parsing.

Forward Air bills by emailing summary-bill PDFs; there is no rating or tracking
API behind this adapter and therefore no client class. That asymmetry with
``carriers.ups`` and ``carriers.fedex`` is deliberate — an adapter models what
the carrier actually offers.

    from carriers.forwardair import parse_file

    inv = parse_file("Inv3793517-2552326.PDF")
    print(inv.number, inv.total_due, len(inv.airbills), inv.errors)

Content problems never raise: unparsable charge lines, totals that fail to
reconcile, and a summary-bill number contradicting the caller's expectation all
land in :attr:`Invoice.errors`. I/O and pdfminer failures *do* propagate — a
missing or corrupt file is the caller's problem to report, not a parse result.

Requires the ``forwardair`` extra::

    pip install 'annex-carriers[forwardair]'

The extra exists so the base package keeps its zero-runtime-dependency promise.
Nothing in ``carriers/__init__.py`` imports this module, so a consumer without
the extra installed never touches pdfminer.
"""
from __future__ import annotations

from pathlib import Path

from .models import Airbill, Invoice, RateItem
from .parser import InvoiceParser, extract_text

__all__ = [
    "Airbill",
    "Invoice",
    "InvoiceParser",
    "RateItem",
    "extract_text",
    "parse_file",
]


def parse_file(pdf_path: str | Path, invoice_number: str | None = None) -> Invoice:
    """Parse one Forward Air invoice PDF into an :class:`Invoice`.

    ``invoice_number`` is the number the caller *expects*; the parser
    cross-checks it against the Summary Bill No printed on the document and
    records a mismatch in :attr:`Invoice.errors`. It defaults to the file stem,
    which is how Forward Air names the attachments (``Inv3793517-2552326.PDF``)
    and preserves the behaviour of the abtool code this replaced.
    """
    path = Path(pdf_path)
    return InvoiceParser(invoice_number or path.stem).parse(str(path))
