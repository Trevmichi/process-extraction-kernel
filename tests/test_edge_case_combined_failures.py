"""
tests/test_edge_case_combined_failures.py
Edge-case tests for the both_terminal_and_field_mismatch failure bucket.

Tests scenarios where multiple failure codes fire simultaneously,
including a regression test reconstructing the exact INV-2024 scenario.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verifier import verify_extraction


RAW_TEXT = (
    "INVOICE #001\n"
    "Vendor: Office Supplies Co\n"
    "Total: $250.00\n"
    "PO: PO-1122"
)


# ---------------------------------------------------------------------------
# All fields missing
# ---------------------------------------------------------------------------

class TestAllFieldsMissing:

    def test_empty_extraction(self):
        """Empty dict → 3x MISSING_KEY."""
        valid, codes, prov = verify_extraction(RAW_TEXT, {})
        assert valid is False
        assert codes.count("MISSING_KEY") == 3

    def test_none_values_for_all_fields(self):
        """All fields present but set to None."""
        ext = {"vendor": None, "amount": None, "has_po": None}
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_KEY" in codes or "WRONG_TYPE" in codes


# ---------------------------------------------------------------------------
# All fields with ungrounded evidence
# ---------------------------------------------------------------------------

class TestAllFieldsUngrounded:

    def test_all_evidence_fabricated(self):
        """All evidence strings are fabricated — not in raw text."""
        ext = {
            "vendor": {
                "value": "Fake Corp",
                "evidence": "Vendor: Totally Nonexistent LLC",
            },
            "amount": {"value": 999.99, "evidence": "Total: $999.99"},
            "has_po": {"value": True, "evidence": "PO: PO-0000"},
        }
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "EVIDENCE_NOT_FOUND" in codes

    def test_all_evidence_empty_strings(self):
        """All evidence is empty string."""
        ext = {
            "vendor": {"value": "Office Supplies Co", "evidence": ""},
            "amount": {"value": 250.00, "evidence": ""},
            "has_po": {"value": True, "evidence": ""},
        }
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_EVIDENCE" in codes


# ---------------------------------------------------------------------------
# Mixed failure types
# ---------------------------------------------------------------------------

class TestMixedFailureTypes:

    def test_missing_vendor_plus_amount_mismatch(self):
        """MISSING_VENDOR + AMOUNT_MISMATCH in the same extraction."""
        ext = {
            "vendor": {
                "value": "",
                "evidence": "Vendor: Office Supplies Co",
            },
            "amount": {"value": 999.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_VENDOR" in codes
        assert "AMOUNT_MISMATCH" in codes

    def test_vendor_mismatch_plus_po_missing(self):
        """VENDOR_EVIDENCE_MISMATCH + PO_PATTERN_MISSING together."""
        raw = "Invoice\nVendor: Real Corp\nTotal: $100.00\nNotes: see attachment"
        ext = {
            "vendor": {
                "value": "Wrong Corp",
                "evidence": "Vendor: Real Corp",
            },
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Notes: see attachment"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "VENDOR_EVIDENCE_MISMATCH" in codes
        assert "PO_PATTERN_MISSING" in codes

    def test_wrong_type_on_multiple_fields(self):
        """Multiple WRONG_TYPE failures at once."""
        ext = {
            "vendor": "not a dict",
            "amount": "not a dict",
            "has_po": "not a dict",
        }
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert codes.count("WRONG_TYPE") == 3


# ---------------------------------------------------------------------------
# Parameterized: combinations of exactly 2 failure codes
# ---------------------------------------------------------------------------

_TWO_FAILURE_CASES = [
    pytest.param(
        {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Delivery scheduled"},
        },
        "PO_PATTERN_MISSING",
        id="valid_vendor_amount_but_po_missing",
    ),
    pytest.param(
        {
            "vendor": {"value": "", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
        "MISSING_VENDOR",
        id="missing_vendor_rest_valid",
    ),
    pytest.param(
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 999.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
        "AMOUNT_MISMATCH",
        id="amount_mismatch_rest_valid",
    ),
]


class TestSingleFieldFailure:
    """Verify that a single bad field produces exactly the expected code."""

    @pytest.mark.parametrize("ext, expected_code", _TWO_FAILURE_CASES)
    def test_isolated_failure(self, ext: dict, expected_code: str):
        # Raw text covers all evidence strings used in the test cases above.
        # The PO test case uses raw text WITHOUT a PO keyword to avoid
        # the 50-char contextual window detecting one.
        if expected_code == "PO_PATTERN_MISSING":
            raw = "Invoice\nVendor: Acme\nTotal: $100.00\nDelivery scheduled"
        else:
            raw = "INVOICE #001\nVendor: Office Supplies Co\nTotal: $250.00\nPO: PO-1122"
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert expected_code in codes


# ---------------------------------------------------------------------------
# INV-2024 exact reconstruction
# ---------------------------------------------------------------------------

class TestINV2024Combined:
    """The INV-2024 eval failure: all 3 fields mismatch because the extraction
    was rejected by the verifier (PO_PATTERN_MISSING → EXCEPTION_BAD_EXTRACTION).
    """

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

    def test_valid_extraction_passes_all_checks(self):
        """With correct evidence, the extraction should pass despite OCR noise."""
        ext = {
            "vendor": {
                "value": "TrueNorth Mechanical Corp",
                "evidence": "TrueNorth Mechanical Corp",
            },
            "amount": {"value": 2956.77, "evidence": "Total: 2956.77"},
            "has_po": {"value": True, "evidence": "PO Number: REF-73225"},
        }
        valid, codes, prov = verify_extraction(self.RAW_TEXT, ext)
        assert valid is True, f"Expected all checks to pass but got codes: {codes}"
        assert prov["vendor"]["grounded"] is True
        assert prov["amount"]["grounded"] is True
        assert prov["has_po"]["grounded"] is True

    def test_bad_evidence_triggers_multiple_failures(self):
        """Completely wrong evidence should trigger failures on all fields."""
        ext = {
            "vendor": {"value": "Wrong Corp", "evidence": "Vendor: Wrong Corp"},
            "amount": {"value": 0.0, "evidence": "Total: $0.00"},
            "has_po": {"value": True, "evidence": "No PO found"},
        }
        valid, codes, _ = verify_extraction(self.RAW_TEXT, ext)
        assert valid is False
        assert len(codes) >= 2  # multiple failures expected
