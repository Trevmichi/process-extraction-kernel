"""
tests/test_edge_case_ocr_noise.py
Edge-case tests for verifier behavior on OCR-degraded invoice text.

Motivated by INV-2024 (failure_bucket: both_terminal_and_field_mismatch),
which is a synthetic OCR-noisy invoice with garbled descriptions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verifier import verify_extraction


# ---------------------------------------------------------------------------
# Whitespace noise — extra spaces within tokens
# ---------------------------------------------------------------------------

class TestWhitespaceNoiseInEvidence:
    """Verifier normalises whitespace; extra spaces should not break grounding."""

    def test_vendor_with_internal_spaces(self):
        raw = "Invoice\nVendor:  Acme   Corp\nTotal: $100.00\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor:  Acme   Corp"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True
        assert "EVIDENCE_NOT_FOUND" not in codes

    def test_amount_evidence_with_leading_spaces(self):
        raw = "Invoice\nVendor: Test Co\n   Total:  $500.00\nPO: PO-2"
        ext = {
            "vendor": {"value": "Test Co", "evidence": "Vendor: Test Co"},
            "amount": {"value": 500.00, "evidence": "   Total:  $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-2"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["amount"]["grounded"] is True
        assert "AMOUNT_MISMATCH" not in codes

    def test_tab_separated_evidence(self):
        raw = "Invoice\nVendor:\tWidgets Inc\nTotal:\t$200.00\nPO: PO-3"
        ext = {
            "vendor": {"value": "Widgets Inc", "evidence": "Vendor:\tWidgets Inc"},
            "amount": {"value": 200.00, "evidence": "Total:\t$200.00"},
            "has_po": {"value": True, "evidence": "PO: PO-3"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True
        assert prov["amount"]["grounded"] is True


# ---------------------------------------------------------------------------
# OCR character substitution — common misreads
# ---------------------------------------------------------------------------

class TestOCRCharacterSubstitution:
    """OCR can substitute visually similar characters (O/0, l/1, etc.)."""

    def test_correct_vendor_despite_noisy_raw_text(self):
        """Raw text has OCR noise in non-evidence areas; evidence itself is clean."""
        raw = (
            "Inv0ice #001\n"  # 0 instead of o — OCR noise
            "Vendor: Clean Corp\n"
            "Tota1: $300.00\n"  # 1 instead of l — OCR noise
            "PO: PO-555"
        )
        ext = {
            "vendor": {"value": "Clean Corp", "evidence": "Vendor: Clean Corp"},
            "amount": {"value": 300.00, "evidence": "$300.00"},
            "has_po": {"value": True, "evidence": "PO: PO-555"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        # Amount evidence "$300.00" should be found even though "Tota1:" is garbled
        assert prov["amount"]["grounded"] is True
        assert "AMOUNT_MISMATCH" not in codes

    def test_amount_in_noisy_table_format(self):
        """Amount evidence should ground even in a noisy table-like layout."""
        raw = (
            "Vendor: TableTest Inc\n"
            "Ite m        Qty   Price\n"
            "---- ----------- -------\n"
            "Widget        2    50.00\n"
            "Gadg et       1    75.00\n"
            "---- ----------- -------\n"
            "Total: 175.00\n"
            "PO: PO-8"
        )
        ext = {
            "vendor": {"value": "TableTest Inc", "evidence": "Vendor: TableTest Inc"},
            "amount": {"value": 175.00, "evidence": "Total: 175.00"},
            "has_po": {"value": True, "evidence": "PO: PO-8"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["parsed_evidence"] == 175.00


# ---------------------------------------------------------------------------
# Unicode noise — non-breaking spaces, em-dashes, smart quotes
# ---------------------------------------------------------------------------

class TestUnicodeNoise:
    """Real-world OCR/PDF extraction often introduces Unicode variants."""

    def test_non_breaking_space_in_vendor(self):
        """Non-breaking space (\\u00a0) between words."""
        vendor = "Delta\u00a0Systems"  # non-breaking space
        raw = f"Invoice\nVendor: {vendor}\nTotal: $800.00\nPO: PO-10"
        ext = {
            "vendor": {"value": "Delta Systems", "evidence": f"Vendor: {vendor}"},
            "amount": {"value": 800.00, "evidence": "Total: $800.00"},
            "has_po": {"value": True, "evidence": "PO: PO-10"},
        }
        # \u00a0 normalises to regular space via \s+ collapse
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True

    def test_em_dash_in_po_evidence(self):
        """Em-dash instead of hyphen in PO reference — should still ground."""
        raw = "Invoice\nVendor: Acme\nTotal: $100.00\nPO: PO\u20141234"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO\u20141234"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        # Evidence should ground (it's in the raw text)
        assert prov["has_po"]["grounded"] is True


# ---------------------------------------------------------------------------
# Multiline evidence — evidence spanning line breaks
# ---------------------------------------------------------------------------

class TestMultilineEvidence:
    """Evidence strings that span line breaks in the original text."""

    def test_vendor_across_lines(self):
        raw = "Invoice\nVendor:\n  Acme Corp International\nTotal: $100.00\nPO: PO-1"
        ext = {
            "vendor": {
                "value": "Acme Corp International",
                "evidence": "Vendor:\n  Acme Corp International",
            },
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True

    def test_amount_with_linebreak_before_total(self):
        raw = "Invoice\nVendor: Test Co\nSubtotal: $80.00\n\nTotal:\n$100.00\nPO: PO-2"
        ext = {
            "vendor": {"value": "Test Co", "evidence": "Vendor: Test Co"},
            "amount": {"value": 100.00, "evidence": "Total:\n$100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-2"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["amount"]["grounded"] is True
        assert "AMOUNT_MISMATCH" not in codes
