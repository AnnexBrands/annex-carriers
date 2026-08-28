"""Forward Air invoice parser tests.

Driven from checked-in *text* fixtures rather than binary PDFs: the state
machine is what these tests are about, and text fixtures stay readable and
diffable in review. ``extract_text`` (the pdfminer boundary) is patched out.

The fixtures encode real incidents from the 07/19/2026 ingest run report, so a
regression in the parser fails here rather than in the database.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from carriers.forwardair import Invoice, InvoiceParser, parser as parser_mod

FIXTURES = Path(__file__).parent / "fixtures"


def parse_fixture(name: str, invoice_number: str, monkeypatch) -> Invoice:
    """Run the state machine over a text fixture, bypassing pdfminer."""
    text = (FIXTURES / name).read_text()
    monkeypatch.setattr(parser_mod, "extract_text", lambda _path: text)
    return InvoiceParser(invoice_number).parse("ignored.PDF")


@pytest.fixture
def clean(monkeypatch) -> Invoice:
    return parse_fixture("invoice_3793517_clean.txt", "3793517", monkeypatch)


# ---- header extraction ----------------------------------------------------

def test_billing_date_extracted(clean):
    assert clean.bill_date == "7/20/26"


def test_summary_bill_number_extracted(clean):
    assert clean.number == "3793517"


def test_amount_due_extracted(clean):
    assert clean.total_due == pytest.approx(917.81)


def test_summary_bill_mismatch_recorded_not_raised(monkeypatch):
    """A number that contradicts the caller's expectation is an error entry,
    not an exception — one bad file must not abort a whole chunk."""
    inv = parse_fixture("invoice_3793517_clean.txt", "9999999", monkeypatch)
    assert any("Wrong bill" in e for e in inv.errors)


# ---- airbill extraction ---------------------------------------------------

def test_all_airbills_found(clean):
    assert set(clean.airbills) == {"96728197", "96734873", "96735396"}


def test_airbill_fields(clean):
    ab = clean.airbills["96728197"]
    assert ab.org_dst == "CMH/CID"
    assert ab.ship_date == "7/13/26"
    assert ab.weight == pytest.approx(497.0)
    assert ab.reweigh == pytest.approx(515.0)
    assert ab.amount_due == pytest.approx(327.88)


def test_reweigh_defaults_to_zero_when_absent(clean):
    assert clean.airbills["96734873"].reweigh == 0.0


def test_weight_with_thousands_separator(monkeypatch):
    inv = parse_fixture("invoice_3767710_flushleft.txt", "3767710", monkeypatch)
    assert inv.airbills["96200090"].weight == pytest.approx(1240.0)


def test_charge_lines_captured(clean):
    ab = clean.airbills["96728197"]
    assert [(r.description, r.amount) for r in ab.rates] == [
        ("CL 500", 250.00),
        ("Fuel Surcharge", 52.88),
        ("Residential Delivery", 25.00),
    ]


# ---- reconciliation -------------------------------------------------------

def test_clean_invoice_has_no_errors(clean):
    assert clean.errors == []


def test_airbill_totals_reconcile(clean):
    for ab in clean.airbills.values():
        assert ab.rate_total == pytest.approx(ab.amount_due, abs=0.01)


def test_invoice_total_reconciles(clean):
    assert clean.airbill_total == pytest.approx(clean.total_due, abs=0.01)


def test_unreconciled_airbill_is_recorded(monkeypatch):
    inv = parse_fixture("invoice_3799001_mismatch.txt", "3799001", monkeypatch)
    assert inv.airbills["96800111"].rate_total == pytest.approx(360.00)
    assert any("96800111" in e and "rate sum" in e for e in inv.errors)


# ---- the flush-left regression (run report §A) -----------------------------
#
# A charge line long enough to render at column 0 was silently dropped by the
# old five-leading-space requirement, understating two airbills by $85.00 each.

def test_flush_left_charge_line_is_captured(monkeypatch):
    inv = parse_fixture("invoice_3767710_flushleft.txt", "3767710", monkeypatch)
    descriptions = [r.description for r in inv.airbills["96200090"].rates]
    assert "Debis Removal 1 (shrink & skid only per unit)" in descriptions


def test_flush_left_line_carries_its_amount(monkeypatch):
    inv = parse_fixture("invoice_3767710_flushleft.txt", "3767710", monkeypatch)
    line = next(r for r in inv.airbills["96200090"].rates if r.description.startswith("Debis"))
    assert line.amount == pytest.approx(85.00)


def test_airbill_reconciles_only_because_flush_left_line_was_captured(monkeypatch):
    """The whole point: dropping that line left the airbill at 816.93 against a
    printed total of 901.93. Reconciliation is the guard that would have caught
    it, so assert both the sum and the absence of an error."""
    inv = parse_fixture("invoice_3767710_flushleft.txt", "3767710", monkeypatch)
    ab = inv.airbills["96200090"]
    assert len(ab.rates) == 11
    assert ab.rate_total == pytest.approx(901.93)
    assert inv.errors == []


# ---- the duplicate airbill (run report §B) --------------------------------
#
# Airbill 96340828 legitimately appears on two invoices as two different legs.
# The parser must read each correctly; detecting the collision across invoices
# is the caller's job, since a parser only ever sees one document.

@pytest.mark.parametrize(
    "fixture,number,org_dst,ship,total,rate_count",
    [
        ("invoice_3773801_dup_leg_a.txt", "3773801", "EWR/JFK", "6/12/26", 183.28, 3),
        ("invoice_3778467_dup_leg_b.txt", "3778467", "MIA/EWR", "6/04/26", 362.54, 5),
    ],
)
def test_duplicate_airbill_legs_each_parse_correctly(
    monkeypatch, fixture, number, org_dst, ship, total, rate_count
):
    inv = parse_fixture(fixture, number, monkeypatch)
    ab = inv.airbills["96340828"]
    assert ab.org_dst == org_dst
    assert ab.ship_date == ship
    assert ab.amount_due == pytest.approx(total)
    assert len(ab.rates) == rate_count
    assert inv.errors == []


# ---- structural guards ----------------------------------------------------

def test_pending_sentinel_never_survives(clean):
    assert "_pending" not in clean.airbills


def test_parse_file_defaults_invoice_number_to_file_stem(monkeypatch, tmp_path):
    from carriers.forwardair import parse_file

    text = (FIXTURES / "invoice_3793517_clean.txt").read_text()
    monkeypatch.setattr(parser_mod, "extract_text", lambda _path: text)
    pdf = tmp_path / "3793517.PDF"
    pdf.write_bytes(b"%PDF-1.4")
    assert parse_file(pdf).number == "3793517"
