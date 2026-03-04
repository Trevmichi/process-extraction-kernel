"""
tests/test_edge_case_amount_disambiguation.py
Edge-case tests for AMBIGUOUS_AMOUNT_EVIDENCE and amount parsing.

Exercises _extract_numbers, _disambiguate_amount, and the keyword-window
logic in _verify_amount with multi-number evidence strings.
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

def _make_ext(vendor: str, amount: float, amount_evidence: str, po: str = "PO: PO-1") -> dict:
    return {
        "vendor": {"value": vendor, "evidence": f"Vendor: {vendor}"},
        "amount": {"value": amount, "evidence": amount_evidence},
        "has_po": {"value": True, "evidence": po},
    }


def _make_raw(vendor: str, body: str, po: str = "PO: PO-1") -> str:
    return f"Invoice\nVendor: {vendor}\n{body}\n{po}"


# ---------------------------------------------------------------------------
# Single number — no disambiguation needed
# ---------------------------------------------------------------------------

class TestSingleNumberEvidence:

    @pytest.mark.parametrize("evidence, expected_val", [
        pytest.param("Total: $1,234.56", 1234.56, id="dollar_with_commas"),
        pytest.param("Total: 99.99", 99.99, id="bare_decimal"),
        pytest.param("Total: $0.01", 0.01, id="one_cent"),
        pytest.param("Total: €10,000.00", 10000.00, id="euro_ten_thousand"),
        pytest.param("Total: £999", 999.0, id="pound_no_decimals"),
        pytest.param("Amount Due: .50", 0.50, id="leading_dot"),
    ])
    def test_single_number_matches(self, evidence: str, expected_val: float):
        raw = _make_raw("Acme", evidence)
        ext = _make_ext("Acme", expected_val, evidence)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes
        assert prov["amount"]["parsed_evidence"] is not None
        assert abs(prov["amount"]["parsed_evidence"] - expected_val) <= 0.01


# ---------------------------------------------------------------------------
# Multi-number with successful keyword disambiguation
# ---------------------------------------------------------------------------

class TestKeywordDisambiguation:

    def test_line_items_plus_total_keyword_resolves(self):
        """'Total' keyword within 30 chars of the correct number only."""
        body = "Widgets: $400.00\nTax: $50.00\nTotal: $450.00"
        raw = _make_raw("TestCo", body)
        ext = _make_ext("TestCo", 450.00, body)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes
        assert "AMOUNT_MISMATCH" not in codes

    def test_amount_due_keyword(self):
        """'Amount Due' keyword disambiguates."""
        body = "Items: $200.00\nShipping: $15.00\nAmount Due: $215.00"
        raw = _make_raw("ShipCo", body)
        ext = _make_ext("ShipCo", 215.00, body)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes

    def test_balance_due_keyword(self):
        """'Balance Due' keyword disambiguates."""
        body = "Previous: $100.00\nPayment: $50.00\nBalance Due: $50.00"
        raw = _make_raw("BalanceCo", body)
        ext = _make_ext("BalanceCo", 50.00, body)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes

    def test_sum_keyword(self):
        """'Sum' keyword disambiguates."""
        body = "Line 1: $10.00\nLine 2: $20.00\nSum: $30.00"
        raw = _make_raw("SumCo", body)
        ext = _make_ext("SumCo", 30.00, body)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes

    def test_three_numbers_with_total_keyword(self):
        """3 numbers in evidence, 'Total' near the last one."""
        body = "Part A: $100.00\nPart B: $200.00\nTotal: $300.00"
        raw = _make_raw("ThreeCo", body)
        ext = _make_ext("ThreeCo", 300.00, body)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes
        assert "AMOUNT_MISMATCH" not in codes


# ---------------------------------------------------------------------------
# Multi-number — disambiguation FAILS (AMBIGUOUS_AMOUNT_EVIDENCE)
# ---------------------------------------------------------------------------

class TestAmbiguousAmountFails:

    def test_two_numbers_no_keyword(self):
        """Two numbers, no disambiguating keyword nearby."""
        body = "Items: 50.00 and 100.00"
        raw = _make_raw("Acme", body)
        ext = _make_ext("Acme", 100.00, body)
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" in codes

    def test_three_numbers_no_keyword(self):
        """Three numbers, no keyword near any of them."""
        body = "Charges: 10.00, 20.00, 30.00"
        raw = _make_raw("NoCo", body)
        ext = _make_ext("NoCo", 30.00, body)
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" in codes

    def test_multiple_keywords_multiple_numbers(self):
        """Two keywords each near a different number — ambiguous."""
        body = "Amount: $100.00\nDue: $200.00"
        raw = _make_raw("DualCo", body)
        ext = _make_ext("DualCo", 200.00, body)
        valid, codes, _ = verify_extraction(raw, ext)
        # Both 100.00 and 200.00 have keywords nearby → ambiguous
        assert valid is False
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" in codes


# ---------------------------------------------------------------------------
# Amount mismatch — parsed number differs from claimed value
# ---------------------------------------------------------------------------

class TestAmountMismatchEdgeCases:

    def test_exact_match_passes(self):
        """Delta of 0.00 should pass."""
        raw = _make_raw("Acme", "Total: $100.00")
        ext = _make_ext("Acme", 100.00, "Total: $100.00")
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["delta"] == 0.0

    def test_half_cent_delta_passes(self):
        """Delta of 0.005 should pass (<= 0.01 tolerance)."""
        raw = _make_raw("Acme", "Total: $100.005")
        ext = _make_ext("Acme", 100.00, "Total: $100.005")
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes

    def test_off_by_five_cents_fails(self):
        """Delta of 0.05 should fail."""
        raw = _make_raw("Acme", "Total: $100.05")
        ext = _make_ext("Acme", 100.00, "Total: $100.05")
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" in codes
        assert prov["amount"]["delta"] > 0.01

    def test_evidence_has_no_parseable_number(self):
        """Evidence contains no numeric content at all."""
        raw = _make_raw("Acme", "Total: TBD")
        ext = _make_ext("Acme", 100.00, "Total: TBD")
        valid, codes, _ = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" in codes

    def test_zero_amount_matches_zero_evidence(self):
        """$0.00 amount with matching evidence should pass."""
        raw = _make_raw("FreeCo", "Total: $0.00")
        ext = _make_ext("FreeCo", 0.00, "Total: $0.00")
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["delta"] == 0.0

    def test_large_amount_with_commas(self):
        """$1,234,567.89 should parse correctly."""
        raw = _make_raw("BigCo", "Total: $1,234,567.89")
        ext = _make_ext("BigCo", 1234567.89, "Total: $1,234,567.89")
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["parsed_evidence"] == 1234567.89


# ---------------------------------------------------------------------------
# Currency symbol edge cases
# ---------------------------------------------------------------------------

class TestCurrencyEdgeCases:

    @pytest.mark.parametrize("symbol, amount_str, expected", [
        pytest.param("$", "$500.00", 500.00, id="dollar"),
        pytest.param("€", "€500.00", 500.00, id="euro"),
        pytest.param("£", "£500.00", 500.00, id="pound"),
        pytest.param("¥", "¥500", 500.00, id="yen"),
        pytest.param("₹", "₹500.00", 500.00, id="rupee"),
    ])
    def test_currency_symbols_stripped(self, symbol: str, amount_str: str, expected: float):
        evidence = f"Total: {amount_str}"
        raw = _make_raw("CurrCo", evidence)
        ext = _make_ext("CurrCo", expected, evidence)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
