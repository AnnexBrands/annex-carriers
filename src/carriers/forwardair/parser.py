"""Forward Air remittance invoice PDF parser.

Extracts billing data from Forward Air PDF invoices using pdfminer
text extraction and a line-by-line state machine.
"""

from __future__ import annotations

import re
from io import StringIO

from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage

from .models import Airbill, Invoice, RateItem


def extract_text(pdf_path: str) -> str:
    rsrcmgr = PDFResourceManager()
    out = StringIO()
    device = TextConverter(rsrcmgr, out, laparams=LAParams())
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    with open(pdf_path, "rb") as f:
        for page in PDFPage.get_pages(f, check_extractable=True):
            interpreter.process_page(page)
    text = out.getvalue()
    device.close()
    out.close()
    return text


# Patterns that signal the end of a rate block (safety net if "Airbill Total" missed)
_RATE_BLOCK_END = ("Pick-Up Location:", "Ship Date:", "Org/Dst:", "Consignee:")

# The leading margin is deliberately NOT constrained.  An earlier version
# required five leading spaces, which silently dropped any charge line long
# enough to render flush-left -- two airbills were understated by $85.00 each
# before the omission was noticed downstream (see the 07/19/2026 run report).
#
# Relaxing the margin admits a theoretical false match on non-rate text, but
# the amount group requires a decimal point (a ZIP or street number cannot
# match), the rate block is already bounded by a "Rate:" opener and the
# _RATE_BLOCK_END phrases, and -- decisively -- a false positive necessarily
# breaks `Airbill.rate_total == Airbill.amount_due`, which lands in
# Invoice.errors.  The old failure mode was a silent understatement; this one
# announces itself.  Callers are expected to surface Invoice.errors for review
# before acting on the parse.
#
# Anchoring on pdfminer's layout coordinates instead of whitespace would be
# more robust still, but that is a rewrite rather than a fix, and the
# total-reconciliation check bounds the damage either way.
_RATE_RE = re.compile(r"(?:Rate:)?\s*(.*\S)\s{3}\s+(\d*,?\d+\.\d+)")


class InvoiceParser:
    """State-machine parser for Forward Air invoice PDF text."""

    def __init__(self, invoice_number: str) -> None:
        self._state = self._await_billdate
        self._inv = Invoice(number=invoice_number)
        self._curr_key: str = "_pending"
        self._pending = Airbill()
        self._in_rate_block = False
        # True once an airbill header could not be read, until the next one is.
        self._orphaned = False

    def parse(self, pdf_path: str) -> Invoice:
        text = extract_text(pdf_path)
        for line in text.splitlines():
            try:
                self._state(line)
            except StopIteration:
                break
            except Exception as e:
                self._inv.errors.append(str(e))
        self._inv.airbills.pop("_pending", None)
        return self._inv

    # -- states ---------------------------------------------------------------

    def _await_billdate(self, line: str) -> None:
        m = re.search(r"Billing Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", line, re.IGNORECASE)
        if m:
            self._inv.bill_date = m.group(1)
            self._state = self._await_inv

    def _await_inv(self, line: str) -> None:
        m = re.search(r"Summary Bill No:\s*(\d{7})", line, re.IGNORECASE)
        if m:
            inv = m.group(1)
            if inv not in self._inv.number:
                raise Exception(f"Wrong bill: expected {self._inv.number}, got {inv}")
            self._inv.number = inv
            self._state = self._await_total_due

    def _await_total_due(self, line: str) -> None:
        m = re.search(r"Amount Due:\s*(\d*,?\d+\.\d+)", line, re.IGNORECASE)
        if m:
            self._inv.total_due = float(m.group(1).replace(",", ""))
            self._state = self._await_airbill_details

    def _await_airbill_details(self, line: str) -> None:
        if self._check_new_awb(line):
            return
        if self._check_orgdst(line):
            return
        if self._check_shipdate(line):
            return
        if self._check_weight(line):
            return
        if self._check_reweigh(line):
            return
        if self._check_rate_line(line):
            return
        if self._check_amount_due(line):
            return
        self._check_delivery_location(line)

    # -- field extractors -----------------------------------------------------

    @property
    def _current(self) -> Airbill:
        if self._curr_key == "_pending":
            return self._pending
        return self._inv.airbills.get(self._curr_key, self._pending)

    def _check_new_awb(self, line: str) -> bool:
        if not line.startswith("Airbill/Invoice No.:"):
            return False
        # Anchored on the label, and NOT restricted to a leading 8 or 9.  An
        # earlier `\b([89]\d{7})\b` silently refused airbill 16617949 and every
        # other number outside the 8xxxxxxx-9xxxxxxx range.
        #
        # Anchoring matters as much as the range: airbills carry a Reference
        # No. that can sit one digit away from the airbill itself (16617949
        # references 96617949), so a bare digit search could bind the wrong one.
        m = re.search(r"Airbill/Invoice No\.:\s*(\d{6,12})", line)
        if not m:
            self._inv.errors.append(f"Could not parse airbill number from: {line}")
            # Everything after this belongs to an airbill we cannot name.  Flag
            # it so the NEXT airbill starts from a clean slate -- otherwise the
            # orphan's rate lines keep accumulating in _pending and are adopted
            # wholesale by the next airbill, inflating its charges by this
            # one's and leaving a total that reconciles against nothing.
            self._orphaned = True
            return False
        bill = m.group(1)
        if bill in self._inv.airbills:
            self._inv.errors.append(f"Duplicate airbill {bill}")
            return False
        if self._orphaned:
            self._pending = Airbill()
            self._orphaned = False
        self._pending.number = bill
        self._inv.airbills[bill] = self._pending
        self._pending = Airbill()
        self._curr_key = bill
        return True

    def _check_orgdst(self, line: str) -> bool:
        m = re.search(r"(?:Org/Dst:\s*)([A-Z]{3}/[A-Z]{3})", line)
        if m:
            self._current.org_dst = m.group(1)
            return True
        return False

    def _check_shipdate(self, line: str) -> bool:
        m = re.search(r"Ship Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", line)
        if m:
            self._current.ship_date = m.group(1)
            return True
        return False

    def _check_weight(self, line: str) -> bool:
        m = re.search(r"^Weight:\s*(\d*,?\d+\.?\d*)", line)
        if m:
            self._current.weight = float(m.group(1).replace(",", ""))
            return True
        return False

    def _check_reweigh(self, line: str) -> bool:
        m = re.search(r"Reweighed Weight\s*(\d*,?\d+\.?\d*)", line)
        if m:
            self._current.reweigh = float(m.group(1).replace(",", ""))
            return True
        return False

    def _check_rate_line(self, line: str) -> bool:
        if line.startswith("Rate:"):
            self._in_rate_block = True

        for phrase in _RATE_BLOCK_END:
            if line.startswith(phrase):
                self._in_rate_block = False

        if not self._in_rate_block:
            return False

        m = _RATE_RE.search(line)
        if m:
            self._current.rates.append(
                RateItem(description=m.group(1), amount=float(m.group(2).replace(",", "")))
            )
            return True
        return False

    def _check_amount_due(self, line: str) -> bool:
        m = re.search(r"(\d*,?\d+\.\d+)\s*Airbill Total", line)
        if m:
            self._in_rate_block = False
            due = float(m.group(1).replace(",", ""))
            ab = self._current
            ab.original = due
            ab.amount_due = due
            self._verify_airbill_total(ab)
            return True
        return False

    def _check_delivery_location(self, line: str) -> None:
        if line.startswith("Delivery Location:"):
            self._curr_key = "_pending"

    def _verify_airbill_total(self, ab: Airbill) -> None:
        rate_sum = ab.rate_total
        if abs(rate_sum - ab.amount_due) > 0.01:
            self._inv.errors.append(
                f"Airbill {ab.number}: rate sum {rate_sum:.2f} != amount due {ab.amount_due:.2f}"
            )
