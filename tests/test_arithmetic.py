"""
tests/test_arithmetic.py
Tests for the deterministic arithmetic consistency layer (Phase 8).
"""
from __future__ import annotations

import pytest

from src.arithmetic import (
    _classify_numbers,
    _check_total_sum,
    _check_tax_rate,
    check_arithmetic,
)


# ===================================================================
# Number classification
# ===================================================================

class TestClassifyNumbers:

    def test_subtotal_keyword(self):
        nums = _classify_numbers("Subtotal: 400.00")
        assert len(nums) == 1
        assert nums[0]["value"] == 400.0
        assert nums[0]["role"] == "subtotal"

    def test_total_keyword(self):
        nums = _classify_numbers("Total Due: 500.00")
        assert any(n["role"] == "total" for n in nums)

    def test_tax_keyword(self):
        nums = _classify_numbers("Tax: 32.00")
        assert nums[0]["role"] == "tax"

    def test_shipping_keyword(self):
        nums = _classify_numbers("Shipping: 15.00")
        assert nums[0]["role"] == "fee"

    def test_no_keyword(self):
        nums = _classify_numbers("Widget 200.00")
        assert nums[0]["role"] is None

    def test_case_insensitive(self):
        nums = _classify_numbers("SUBTOTAL: 100.00")
        assert nums[0]["role"] == "subtotal"

    def test_currency_stripped(self):
        nums = _classify_numbers("Total: $1,234.56")
        total_nums = [n for n in nums if n["role"] == "total"]
        assert len(total_nums) == 1
        assert total_nums[0]["value"] == 1234.56

    def test_subtotal_before_total(self):
        """'subtotal' keyword should not be misclassified as 'total'."""
        nums = _classify_numbers("Subtotal: 300.00\nTotal: 400.00")
        roles = [(n["value"], n["role"]) for n in nums]
        assert (300.0, "subtotal") in roles
        assert (400.0, "total") in roles


# ===================================================================
# Check A: total sum
# ===================================================================

class TestCheckTotalSum:

    def test_happy_path(self):
        classified = _classify_numbers(
            "Subtotal: 400.00\nTax: 32.00\nShipping: 15.00\nTotal: 447.00"
        )
        code, prov = _check_total_sum(classified)
        assert code is None
        assert prov is not None
        assert prov["delta"] == 0.0

    def test_mismatch(self):
        classified = _classify_numbers(
            "Subtotal: 200.00\nTax: 0.00\nTotal: 500.00"
        )
        code, prov = _check_total_sum(classified)
        assert code == "ARITH_TOTAL_MISMATCH"
        assert prov["expected"] == 200.0
        assert prov["actual"] == 500.0

    def test_missing_subtotal_skips(self):
        classified = _classify_numbers("Total: 500.00")
        code, prov = _check_total_sum(classified)
        assert code is None
        assert prov is None

    def test_missing_total_skips(self):
        classified = _classify_numbers("Subtotal: 300.00")
        code, prov = _check_total_sum(classified)
        assert code is None
        assert prov is None

    def test_zero_tax_subtotal_equals_total(self):
        classified = _classify_numbers(
            "Subtotal: 250.00\nTotal: 250.00"
        )
        code, prov = _check_total_sum(classified)
        assert code is None

    def test_tolerance_boundary_pass(self):
        """Delta of exactly 0.01 should pass."""
        classified = _classify_numbers(
            "Subtotal: 100.00\nTotal: 100.01"
        )
        code, prov = _check_total_sum(classified)
        assert code is None

    def test_tolerance_boundary_fail(self):
        """Delta of 0.02 should fail."""
        classified = _classify_numbers(
            "Subtotal: 100.00\nTotal: 100.02"
        )
        code, prov = _check_total_sum(classified)
        assert code == "ARITH_TOTAL_MISMATCH"

    def test_multiple_fees(self):
        classified = _classify_numbers(
            "Subtotal: 350.00\n"
            "Hazard Pay Surcharge: 50.00\n"
            "Environmental Fee: 15.00\n"
            "Total: 415.00"
        )
        code, prov = _check_total_sum(classified)
        assert code is None
        assert prov["fees"] == 65.0


# ===================================================================
# Check B: tax rate
# ===================================================================

class TestCheckTaxRate:

    def test_happy_path(self):
        text = "Subtotal: 1255.55\nTax (8%): 100.44\nTotal: 1399.11"
        classified = _classify_numbers(text)
        code, prov = _check_tax_rate(text, classified)
        assert code is None
        assert prov is not None
        assert prov["rate_pct"] == 8.0

    def test_rate_mismatch(self):
        text = "Subtotal: 1000.00\nTax (10%): 200.00\nTotal: 1200.00"
        classified = _classify_numbers(text)
        code, prov = _check_tax_rate(text, classified)
        assert code == "ARITH_TAX_RATE_MISMATCH"
        assert prov["computed"] == 100.0
        assert prov["stated"] == 200.0

    def test_no_rate_skips(self):
        text = "Subtotal: 400.00\nTax: 32.00\nTotal: 432.00"
        classified = _classify_numbers(text)
        code, prov = _check_tax_rate(text, classified)
        assert code is None
        assert prov is None

    def test_decimal_rate(self):
        text = "Subtotal: 1000.00\nVAT (7.5%): 75.00\nTotal: 1075.00"
        classified = _classify_numbers(text)
        code, prov = _check_tax_rate(text, classified)
        assert code is None
        assert prov["rate_pct"] == 7.5

    def test_no_subtotal_skips(self):
        text = "Tax (8%): 40.00\nTotal: 540.00"
        classified = _classify_numbers(text)
        code, prov = _check_tax_rate(text, classified)
        assert code is None
        assert prov is None


# ===================================================================
# No-op / skip behavior
# ===================================================================

class TestNoOp:

    def test_simple_total_only(self):
        """Invoice with only Total — no checks run, no audit event."""
        codes, prov = check_arithmetic("Total: $500.00")
        assert codes == []
        assert prov is None

    def test_subtotal_no_total(self):
        codes, prov = check_arithmetic("Subtotal: 300.00\nWidget: 300.00")
        assert codes == []
        assert prov is None

    def test_tax_rate_no_subtotal(self):
        codes, prov = check_arithmetic("Tax (8%): 40.00\nTotal: 540.00")
        assert codes == []
        assert prov is None


# ===================================================================
# Integration: check_arithmetic public API
# ===================================================================

class TestCheckArithmetic:

    def test_consistent_invoice(self):
        text = (
            "Subtotal: 400.00\n"
            "Tax (8%): 32.00\n"
            "Shipping: 15.00\n"
            "Total Amount Due: 447.00"
        )
        codes, prov = check_arithmetic(text)
        assert codes == []
        assert prov is not None
        assert prov["passed"] is True
        assert "total_sum" in prov["checks_run"]
        assert "tax_rate" in prov["checks_run"]

    def test_inconsistent_total(self):
        text = (
            "Subtotal: 200.00\n"
            "Tax: 0.00\n"
            "Total: 500.00"
        )
        codes, prov = check_arithmetic(text)
        assert "ARITH_TOTAL_MISMATCH" in codes
        assert prov["passed"] is False


# ===================================================================
# Gold invoice integration
# ===================================================================

class TestGoldInvoices:

    def _read_gold(self, name: str) -> str:
        import pathlib
        path = pathlib.Path("datasets/gold_invoices") / name
        return path.read_text()

    def test_inv_004_subtotal_tax_shipping(self):
        """inv_004: Subtotal 400 + Tax 32 + Shipping 15 = Total 447."""
        text = self._read_gold("inv_004.txt")
        codes, prov = check_arithmetic(text)
        assert codes == [], f"Unexpected codes: {codes}"

    def test_inv_030_line_items_surcharge_tax(self):
        """inv_030: Line items + Subtotal 350 + Surcharge 50 + Tax 15 = Total 415."""
        text = self._read_gold("inv_030.txt")
        codes, prov = check_arithmetic(text)
        assert codes == [], f"Unexpected codes: {codes}"

    def test_inv_016_subtotal_fee_taxes(self):
        """inv_016: Subtotal 2000 + Processing Fee 20 + Taxes 160 = Final Total 2180."""
        text = self._read_gold("inv_016.txt")
        codes, prov = check_arithmetic(text)
        assert codes == [], f"Unexpected codes: {codes}"
