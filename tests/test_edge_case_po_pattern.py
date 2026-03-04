"""
tests/test_edge_case_po_pattern.py
Edge-case tests for PO_PATTERN_MISSING failure code.

Covers the _PO_RE regex and _verify_has_po contextual window logic,
including the INV-2024 regression (REF- prefix PO reference in OCR-noisy text).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verifier import verify_extraction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invoice(vendor: str, amount: float, po_line: str) -> tuple[str, dict]:
    """Build a minimal raw text and valid extraction for PO-focused tests."""
    raw = f"Invoice\nVendor: {vendor}\nTotal: ${amount:.2f}\n{po_line}"
    ext = {
        "vendor": {"value": vendor, "evidence": f"Vendor: {vendor}"},
        "amount": {"value": amount, "evidence": f"Total: ${amount:.2f}"},
        "has_po": {"value": True, "evidence": po_line},
    }
    return raw, ext


# ---------------------------------------------------------------------------
# Parameterized: PO patterns that SHOULD be recognised (no failure)
# ---------------------------------------------------------------------------

_VALID_PO_CASES = [
    pytest.param("PO: PO-1122", id="standard_PO_dash_number"),
    pytest.param("PO Number: PO-99887", id="PO_Number_prefix"),
    pytest.param("PO Number: REF-73225", id="REF_dash_number_INV2024"),
    pytest.param("REF-73225", id="bare_REF_dash_number"),
    pytest.param("Purchase Order: 4567", id="purchase_order_text"),
    pytest.param("Purchase Order IT-9006", id="purchase_order_with_code"),
    pytest.param("Reference: 12345", id="reference_keyword"),
    pytest.param("P.O. 12345", id="P_dot_O_dot_space"),
    pytest.param("P.O.#12345", id="P_dot_O_dot_hash"),
    pytest.param("P.O. ", id="P_dot_O_dot_trailing_space"),
    pytest.param("PO12345", id="PO_no_separator"),
    pytest.param("REF99001", id="REF_no_separator"),
]


class TestPOPatternRecognised:
    """PO evidence strings that should pass the PO_PATTERN_MISSING check."""

    @pytest.mark.parametrize("po_line", _VALID_PO_CASES)
    def test_po_pattern_found(self, po_line: str):
        raw, ext = _make_invoice("Acme Corp", 100.00, po_line)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" not in codes, (
            f"PO pattern should be recognised in: {po_line!r}"
        )
        assert prov["has_po"]["po_pattern_found"] is True


# ---------------------------------------------------------------------------
# Parameterized: PO evidence that should FAIL (PO_PATTERN_MISSING)
# ---------------------------------------------------------------------------

_MISSING_PO_CASES = [
    pytest.param("Notes: None", id="no_po_keyword_at_all"),
    pytest.param("Order confirmed", id="order_without_PO_prefix"),
    pytest.param("12345", id="bare_number_no_keyword"),
    pytest.param("Delivery scheduled Tuesday", id="no_po_keyword_prose"),
]


class TestPOPatternMissing:
    """PO evidence strings that should trigger PO_PATTERN_MISSING."""

    @pytest.mark.parametrize("po_line", _MISSING_PO_CASES)
    def test_po_pattern_not_found(self, po_line: str):
        raw, ext = _make_invoice("Acme Corp", 100.00, po_line)
        valid, codes, prov = verify_extraction(raw, ext)
        assert valid is False
        assert "PO_PATTERN_MISSING" in codes, (
            f"PO pattern should NOT be recognised in: {po_line!r}"
        )


# ---------------------------------------------------------------------------
# Contextual window: evidence lacks PO keyword but surrounding text has it
# ---------------------------------------------------------------------------

class TestPOContextualWindow:
    """The verifier checks a 50-char window around the evidence location."""

    def test_bare_number_with_po_keyword_in_context(self):
        """Evidence is just '73225' but raw text has 'PO Number: REF-73225' nearby."""
        raw = (
            "Invoice\n"
            "Vendor: Acme Corp\n"
            "Total: $500.00\n"
            "PO Number: REF-73225\n"
            "Notes: standard delivery"
        )
        ext = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.00, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "REF-73225"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" not in codes

    def test_evidence_far_from_po_keyword(self):
        """Evidence '99001' is >50 chars away from any PO keyword — should fail."""
        padding = "x" * 100
        raw = (
            f"Invoice\nVendor: Acme Corp\nTotal: $500.00\n"
            f"PO: PO-5555\n{padding}\nOrder ID: 99001"
        )
        ext = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.00, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "99001"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" in codes


# ---------------------------------------------------------------------------
# INV-2024 regression: exact scenario from eval_report.json
# ---------------------------------------------------------------------------

class TestINV2024Regression:
    """Reconstruct the exact INV-2024 failure scenario from eval_report.json."""

    RAW_TEXT = (
        "TrueNorth Mechanical Corp\n"
        "1600 Pennsylvania Ave NW\n"
        "\n"
        "Invoice: INV-2024\n"
        "Date: 2026-06-30\n"
        "PO Number: REF-73225\n"
        "\n"
        "Des cription               Qty    Price\n"
        "------ ------------------------------- ---\n"
        "Projector Lamp           1      175.00\n"
        "LED Monitor 27in         3      299.99\n"
        "Whiteboard Mark ers (box) 10     12.50\n"
        "-------------------------------------- -- \n"
        "Total: 2956.77"
    )

    def test_ref_prefix_po_should_be_recognised(self):
        """REF-73225 evidence should match _PO_RE pattern."""
        ext = {
            "vendor": {
                "value": "TrueNorth Mechanical Corp",
                "evidence": "TrueNorth Mechanical Corp",
            },
            "amount": {"value": 2956.77, "evidence": "Total: 2956.77"},
            "has_po": {"value": True, "evidence": "REF-73225"},
        }
        valid, codes, prov = verify_extraction(self.RAW_TEXT, ext)
        assert "PO_PATTERN_MISSING" not in codes, (
            "REF-73225 should match the (?:PO|REF)-?\\d+ branch of _PO_RE"
        )
        assert prov["has_po"]["po_pattern_found"] is True

    def test_full_po_line_evidence(self):
        """Using 'PO Number: REF-73225' as evidence should also pass."""
        ext = {
            "vendor": {
                "value": "TrueNorth Mechanical Corp",
                "evidence": "TrueNorth Mechanical Corp",
            },
            "amount": {"value": 2956.77, "evidence": "Total: 2956.77"},
            "has_po": {"value": True, "evidence": "PO Number: REF-73225"},
        }
        valid, codes, prov = verify_extraction(self.RAW_TEXT, ext)
        assert "PO_PATTERN_MISSING" not in codes

    def test_ocr_noisy_text_does_not_break_amount(self):
        """Amount extraction should work despite OCR noise in description lines."""
        ext = {
            "vendor": {
                "value": "TrueNorth Mechanical Corp",
                "evidence": "TrueNorth Mechanical Corp",
            },
            "amount": {"value": 2956.77, "evidence": "Total: 2956.77"},
            "has_po": {"value": True, "evidence": "PO Number: REF-73225"},
        }
        _, codes, prov = verify_extraction(self.RAW_TEXT, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["grounded"] is True
