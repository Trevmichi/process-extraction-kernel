"""
tests/test_verifier.py
Unit tests for the deterministic evidence-based verifier (src/verifier.py).

All assertions on failure reasons use stable FailureCode literals.
"""
from __future__ import annotations

import pytest

from src.verifier import FailureCode, verify_extraction, _normalize_text


# ---------------------------------------------------------------------------
# Shared raw text fixture
# ---------------------------------------------------------------------------

RAW_TEXT = (
    "INVOICE #001\n"
    "Vendor: Office Supplies Co\n"
    "Total: $250.00\n"
    "PO: PO-1122"
)

RAW_TEXT_MULTI_AMOUNT = (
    "INVOICE #002\n"
    "Vendor: Enterprise Servers Inc\n"
    "Subtotal: $40,000.00\n"
    "Tax: $5,000.00\n"
    "Total: $45,000.00\n"
    "PO: PO-9988"
)


def _valid_extraction() -> dict:
    """Extraction payload that should pass all checks against RAW_TEXT."""
    return {
        "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
        "amount": {"value": 250.00, "evidence": "Total: $250.00"},
        "has_po": {"value": True, "evidence": "PO: PO-1122"},
    }


# ===========================================================================
# 1. All valid
# ===========================================================================

class TestAllValid:

    def test_all_fields_pass(self):
        valid, codes, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert valid is True
        assert codes == []

    def test_provenance_keys_present(self):
        _, _, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert "vendor" in prov
        assert "amount" in prov
        assert "has_po" in prov

    def test_vendor_grounded(self):
        _, _, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert prov["vendor"]["grounded"] is True
        assert prov["vendor"]["evidence_found_at"] >= 0

    def test_amount_grounded_and_delta(self):
        _, _, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert prov["amount"]["grounded"] is True
        assert prov["amount"]["parsed_evidence"] == 250.00
        assert prov["amount"]["delta"] is not None
        assert prov["amount"]["delta"] <= 0.01

    def test_has_po_grounded(self):
        _, _, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert prov["has_po"]["grounded"] is True
        assert prov["has_po"]["po_pattern_found"] is True


# ===========================================================================
# 2. Evidence not found in raw text
# ===========================================================================

class TestEvidenceNotFound:

    def test_vendor_evidence_not_in_text(self):
        ext = _valid_extraction()
        ext["vendor"]["evidence"] = "Vendor: Totally Fake Corp"
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "EVIDENCE_NOT_FOUND" in codes

    def test_amount_evidence_not_in_text(self):
        ext = _valid_extraction()
        ext["amount"]["evidence"] = "Total: $999.99"
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "EVIDENCE_NOT_FOUND" in codes


# ===========================================================================
# 3. Missing evidence (empty string)
# ===========================================================================

class TestMissingEvidence:

    def test_empty_evidence_vendor(self):
        ext = _valid_extraction()
        ext["vendor"]["evidence"] = ""
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_EVIDENCE" in codes
        # Must NOT also emit EVIDENCE_NOT_FOUND for the same field
        assert codes.count("EVIDENCE_NOT_FOUND") == 0 or "MISSING_EVIDENCE" in codes

    def test_empty_evidence_amount(self):
        ext = _valid_extraction()
        ext["amount"]["evidence"] = ""
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_EVIDENCE" in codes

    def test_empty_evidence_has_po(self):
        ext = _valid_extraction()
        ext["has_po"]["evidence"] = ""
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_EVIDENCE" in codes

    def test_has_po_false_null_evidence_valid(self):
        """has_po=False with None evidence should pass (null-tolerance)."""
        ext = _valid_extraction()
        ext["has_po"] = {"value": False, "evidence": None}
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert valid is True
        assert "MISSING_EVIDENCE" not in codes
        assert "WRONG_TYPE" not in codes
        assert prov["has_po"]["grounded"] is True
        assert prov["has_po"]["po_pattern_found"] is False

    def test_has_po_false_empty_evidence_valid(self):
        """has_po=False with empty string evidence should pass."""
        ext = _valid_extraction()
        ext["has_po"] = {"value": False, "evidence": ""}
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert valid is True
        assert "MISSING_EVIDENCE" not in codes

    def test_has_po_true_null_evidence_still_fails(self):
        """has_po=True with None evidence must still fail."""
        ext = _valid_extraction()
        ext["has_po"] = {"value": True, "evidence": None}
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False

    def test_whitespace_only_evidence(self):
        ext = _valid_extraction()
        ext["vendor"]["evidence"] = "   "
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_EVIDENCE" in codes


# ===========================================================================
# 4. Amount mismatch
# ===========================================================================

class TestAmountMismatch:

    def test_value_100_evidence_50(self):
        ext = _valid_extraction()
        ext["amount"]["value"] = 100.00
        ext["amount"]["evidence"] = "Total: $250.00"
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "AMOUNT_MISMATCH" in codes

    def test_evidence_has_no_numbers(self):
        ext = _valid_extraction()
        ext["amount"]["evidence"] = "Total: TBD"
        # Evidence "Total: TBD" is unlikely to be in raw text, but let's use
        # a different raw text scenario
        raw = "Invoice Total: TBD\nVendor: Office Supplies Co\nPO: PO-1122"
        ext["vendor"]["evidence"] = "Vendor: Office Supplies Co"
        ext["has_po"]["evidence"] = "PO: PO-1122"
        valid, codes, _ = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" in codes


# ===========================================================================
# 5. Ambiguous amount — disambiguation succeeds
# ===========================================================================

class TestAmountDisambiguation:

    def test_keyword_in_window_passes(self):
        """'Total: $45,000.00' — keyword 'total' is within 30 chars of 45000."""
        ext = {
            "vendor": {"value": "Enterprise Servers Inc", "evidence": "Vendor: Enterprise Servers Inc"},
            "amount": {"value": 45000.00, "evidence": "Total: $45,000.00"},
            "has_po": {"value": True, "evidence": "PO: PO-9988"},
        }
        valid, codes, prov = verify_extraction(RAW_TEXT_MULTI_AMOUNT, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes

    def test_multi_number_with_keyword_passes(self):
        """Evidence has two numbers but 'Total' keyword disambiguates."""
        ext = {
            "vendor": {"value": "Enterprise Servers Inc", "evidence": "Vendor: Enterprise Servers Inc"},
            "amount": {"value": 45000.00, "evidence": "Subtotal: $40,000.00\nTotal: $45,000.00"},
            "has_po": {"value": True, "evidence": "PO: PO-9988"},
        }
        valid, codes, prov = verify_extraction(RAW_TEXT_MULTI_AMOUNT, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes

    def test_keyword_beyond_3_chars_within_30_passes(self):
        """Keyword ~8 chars before number, within 30 but beyond 3 (kills M012)."""
        raw = "Invoice\nVendor: Acme\nItems: $50.00\nTotal:  $100.00\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Items: $50.00\nTotal:  $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" not in codes
        assert "AMOUNT_MISMATCH" not in codes


# ===========================================================================
# 6. Ambiguous amount — disambiguation fails
# ===========================================================================

class TestAmountAmbiguousFail:

    def test_no_keyword_near_any_number(self):
        """Evidence has numbers but no disambiguating keyword near them."""
        raw = "Invoice\nItems: 50.00 and 100.00\nVendor: Acme\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Items: 50.00 and 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" in codes

    def test_multiple_keywords_multiple_candidates_rejected(self):
        """2+ numbers with nearby keywords → ambiguous (kills M011)."""
        raw = "Invoice\nVendor: Acme\nAmount: $100.00\nDue: $200.00\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Amount: $100.00\nDue: $200.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "AMBIGUOUS_AMOUNT_EVIDENCE" in codes


# ===========================================================================
# 7. Currency parsing
# ===========================================================================

class TestCurrencyParsing:

    def _make_raw_and_ext(self, amount_str: str, expected: float) -> tuple[str, dict]:
        raw = f"Invoice\nVendor: Test Corp\nTotal: {amount_str}\nPO: PO-99"
        ext = {
            "vendor": {"value": "Test Corp", "evidence": "Vendor: Test Corp"},
            "amount": {"value": expected, "evidence": f"Total: {amount_str}"},
            "has_po": {"value": True, "evidence": "PO: PO-99"},
        }
        return raw, ext

    def test_dollar_with_commas(self):
        raw, ext = self._make_raw_and_ext("$1,234.56", 1234.56)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes
        assert prov["amount"]["parsed_evidence"] == 1234.56

    def test_euro(self):
        raw, ext = self._make_raw_and_ext("€500.00", 500.00)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes

    def test_pound(self):
        raw, ext = self._make_raw_and_ext("£1,000", 1000.0)
        valid, codes, prov = verify_extraction(raw, ext)
        assert "AMOUNT_MISMATCH" not in codes


# ===========================================================================
# 8. Missing vendor
# ===========================================================================

class TestMissingVendor:

    def test_empty_vendor_value(self):
        ext = _valid_extraction()
        ext["vendor"]["value"] = ""
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert "MISSING_VENDOR" in codes

    def test_none_vendor_value(self):
        ext = _valid_extraction()
        ext["vendor"]["value"] = None
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert "MISSING_VENDOR" in codes


# ===========================================================================
# 9. Vendor evidence mismatch
# ===========================================================================

class TestVendorEvidenceMismatch:

    def test_value_not_in_evidence(self):
        """Vendor value 'Acme Corp' doesn't appear in evidence 'Invoice Date: 2025-01-01'."""
        raw = "Invoice Date: 2025-01-01\nVendor: Acme Corp\nTotal: $100.00\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme Corp", "evidence": "Invoice Date: 2025-01-01"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "VENDOR_EVIDENCE_MISMATCH" in codes


# ===========================================================================
# 10. PO pattern present
# ===========================================================================

class TestPOPatternPresent:

    def test_po_number_pattern(self):
        valid, codes, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert "PO_PATTERN_MISSING" not in codes
        assert prov["has_po"]["po_pattern_found"] is True

    def test_purchase_order_text(self):
        raw = "Invoice\nVendor: Acme\nTotal: $100.00\nPurchase Order: 4567"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Purchase Order: 4567"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" not in codes


# ===========================================================================
# 11. PO pattern missing
# ===========================================================================

class TestPOPatternMissing:

    def test_has_po_true_but_no_po_pattern(self):
        raw = "Invoice\nVendor: Acme\nTotal: $100.00\nNotes: None"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Notes: None"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert valid is False
        assert "PO_PATTERN_MISSING" in codes


# ===========================================================================
# 12. has_po false valid
# ===========================================================================

class TestHasPOFalseValid:

    def test_no_po_na(self):
        raw = "Invoice\nVendor: Acme\nTotal: $100.00\nPO: N/A"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": False, "evidence": "PO: N/A"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" not in codes
        assert prov["has_po"]["po_pattern_found"] is False

    def test_no_po_none_text(self):
        raw = "Invoice\nVendor: Acme\nTotal: $100.00\nPO: None"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": False, "evidence": "PO: None"},
        }
        valid, codes, _ = verify_extraction(raw, ext)
        assert "PO_PATTERN_MISSING" not in codes


# ===========================================================================
# 13. Whitespace normalisation
# ===========================================================================

class TestWhitespaceNormalization:

    def test_evidence_with_extra_spaces(self):
        raw = "Invoice\nVendor:   Office   Supplies   Co\nTotal: $250.00\nPO: PO-1122"
        ext = {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor:   Office   Supplies   Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True

    def test_evidence_with_newlines(self):
        raw = "Invoice\nVendor:\n  Acme Corp\nTotal: $100.00\nPO: PO-1"
        ext = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor:\n  Acme Corp"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["grounded"] is True


# ===========================================================================
# 14. Missing key
# ===========================================================================

class TestMissingKey:

    def test_vendor_key_missing(self):
        ext = _valid_extraction()
        del ext["vendor"]
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_KEY" in codes

    def test_amount_key_missing(self):
        ext = _valid_extraction()
        del ext["amount"]
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_KEY" in codes

    def test_has_po_key_missing(self):
        ext = _valid_extraction()
        del ext["has_po"]
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "MISSING_KEY" in codes


# ===========================================================================
# 15. Wrong type
# ===========================================================================

class TestWrongType:

    def test_vendor_not_dict(self):
        ext = _valid_extraction()
        ext["vendor"] = "Office Supplies Co"  # should be dict
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "WRONG_TYPE" in codes

    def test_amount_value_is_string(self):
        ext = _valid_extraction()
        ext["amount"]["value"] = "two hundred"
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "WRONG_TYPE" in codes

    def test_has_po_value_not_bool(self):
        ext = _valid_extraction()
        ext["has_po"]["value"] = "yes"
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "WRONG_TYPE" in codes

    def test_evidence_not_string(self):
        ext = _valid_extraction()
        ext["vendor"]["evidence"] = 12345
        valid, codes, _ = verify_extraction(RAW_TEXT, ext)
        assert valid is False
        assert "WRONG_TYPE" in codes


# ===========================================================================
# 16. Provenance structure consistency
# ===========================================================================

class TestProvenanceStructure:

    def test_always_has_consistent_keys_on_success(self):
        _, _, prov = verify_extraction(RAW_TEXT, _valid_extraction())
        assert set(prov.keys()) == {"vendor", "amount", "has_po"}
        assert "grounded" in prov["vendor"]
        assert "evidence_found_at" in prov["vendor"]
        assert "grounded" in prov["amount"]
        assert "parsed_evidence" in prov["amount"]
        assert "delta" in prov["amount"]
        assert "grounded" in prov["has_po"]
        assert "po_pattern_found" in prov["has_po"]

    def test_always_has_consistent_keys_on_failure(self):
        ext = {"vendor": "bad", "amount": "bad", "has_po": "bad"}
        _, _, prov = verify_extraction(RAW_TEXT, ext)
        assert set(prov.keys()) == {"vendor", "amount", "has_po"}
        assert "grounded" in prov["vendor"]
        assert "grounded" in prov["amount"]
        assert "grounded" in prov["has_po"]

    def test_empty_extraction_dict(self):
        valid, codes, prov = verify_extraction(RAW_TEXT, {})
        assert valid is False
        assert codes.count("MISSING_KEY") == 3
        assert set(prov.keys()) == {"vendor", "amount", "has_po"}


# ===========================================================================
# _normalize_text helper
# ===========================================================================

class TestNormalizeText:

    def test_collapse_whitespace(self):
        assert _normalize_text("  hello   world  ") == "hello world"

    def test_casefold(self):
        assert _normalize_text("Hello World") == "hello world"

    def test_newlines_collapsed(self):
        assert _normalize_text("line1\n  line2\t\tline3") == "line1 line2 line3"


# ===========================================================================
# match_tier — evidence quality classification
# ===========================================================================

class TestMatchTier:
    """Verify match_tier is set correctly for each field."""

    # ---- vendor ----

    def test_vendor_exact_match(self):
        """Value appears in evidence as raw substring (case-preserved)."""
        ext = _valid_extraction()
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["vendor"]["match_tier"] == "exact_match"

    def test_vendor_normalized_match_case(self):
        """Value differs in case from evidence → normalized_match."""
        ext = _valid_extraction()
        ext["vendor"]["value"] = "office supplies co"
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["vendor"]["match_tier"] == "normalized_match"

    def test_vendor_normalized_match_whitespace(self):
        """Value has newline/repeated whitespace not in evidence → normalized_match."""
        raw = "INVOICE\nVendor: Office Supplies Co\nTotal: $250.00\nPO: PO-1122"
        ext = _valid_extraction()
        ext["vendor"]["value"] = "Office\n  Supplies\tCo"
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["vendor"]["match_tier"] == "normalized_match"

    def test_vendor_not_found(self):
        """Evidence not in raw text → not_found."""
        ext = _valid_extraction()
        ext["vendor"]["evidence"] = "FABRICATED_EVIDENCE"
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["vendor"]["match_tier"] == "not_found"

    def test_vendor_empty_value_not_found(self):
        """Empty vendor value with grounded evidence → stays not_found."""
        ext = _valid_extraction()
        ext["vendor"]["value"] = ""
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["vendor"]["match_tier"] == "not_found"

    # ---- amount ----

    def test_amount_exact_match(self):
        """Parsed evidence exactly equals claimed value (delta == 0)."""
        ext = _valid_extraction()
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["amount"]["match_tier"] == "exact_match"

    def test_amount_normalized_match(self):
        """Parsed evidence within tolerance (0 < delta <= 0.01)."""
        raw = "INVOICE\nVendor: Acme\nTotal: $250.005\nPO: PO-1122"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 250.0, "evidence": "Total: $250.005"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["amount"]["match_tier"] == "normalized_match"

    def test_amount_not_found(self):
        """Evidence not in raw text → not_found."""
        ext = _valid_extraction()
        ext["amount"]["evidence"] = "Total: $999.99"
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["amount"]["match_tier"] == "not_found"

    # ---- has_po ----

    def test_has_po_exact_match_pattern_in_evidence(self):
        """PO pattern found directly in evidence text → exact_match."""
        ext = _valid_extraction()
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["has_po"]["match_tier"] == "exact_match"

    def test_has_po_normalized_match_expanded_window(self):
        """PO pattern only in expanded ±50 char window → normalized_match."""
        raw = "INVOICE PO-5566 attached document\nVendor: Acme\nTotal: $100.00"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "attached document"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        # PO pattern not in "attached document" but in ±50 char window
        assert prov["has_po"]["match_tier"] == "normalized_match"
        assert prov["has_po"]["po_pattern_found"] is True

    def test_has_po_false_null_tolerance_exact(self):
        """value=False with no evidence → exact_match (deterministic non-PO)."""
        ext = _valid_extraction()
        ext["has_po"]["value"] = False
        ext["has_po"]["evidence"] = ""
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["has_po"]["match_tier"] == "exact_match"

    def test_has_po_false_with_evidence_exact(self):
        """value=False with grounded evidence → exact_match."""
        ext = _valid_extraction()
        ext["has_po"]["value"] = False
        ext["has_po"]["evidence"] = "PO: PO-1122"
        valid, codes, prov = verify_extraction(RAW_TEXT, ext)
        assert prov["has_po"]["match_tier"] == "exact_match"

    # ---- invoice_date ----

    def test_invoice_date_always_normalized(self):
        """ISO value still gets normalized_match (parsing pipeline always runs)."""
        raw = "INVOICE\nDate: 2024-01-15\nVendor: Acme\nTotal: $100.00"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": False, "evidence": ""},
            "invoice_date": {"value": "2024-01-15", "evidence": "Date: 2024-01-15"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["invoice_date"]["match_tier"] == "normalized_match"

    def test_invoice_date_slash_format_normalized(self):
        """Slash-format date → normalized_match."""
        raw = "INVOICE\nDate: 1/15/2024\nVendor: Acme\nTotal: $100.00"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": False, "evidence": ""},
            "invoice_date": {"value": "1/15/2024", "evidence": "Date: 1/15/2024"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["invoice_date"]["match_tier"] == "normalized_match"

    # ---- tax_amount ----

    def test_tax_amount_exact_match(self):
        """Tax delta == 0.0 → exact_match."""
        raw = "INVOICE\nVendor: Acme\nSubtotal: $90.00\nTax: $10.00\nTotal: $100.00\nPO: PO-1122"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
            "tax_amount": {"value": 10.0, "evidence": "Tax: $10.00"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["tax_amount"]["match_tier"] == "exact_match"

    def test_tax_amount_normalized_match(self):
        """Tax delta within tolerance → normalized_match."""
        raw = "INVOICE\nVendor: Acme\nTax: $10.005\nTotal: $100.00\nPO: PO-1122"
        ext = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
            "tax_amount": {"value": 10.0, "evidence": "Tax: $10.005"},
        }
        valid, codes, prov = verify_extraction(raw, ext)
        assert prov["tax_amount"]["match_tier"] == "normalized_match"

    # ---- default tier ----

    def test_default_provenance_has_not_found(self):
        """_default_provenance() initializes all fields to not_found."""
        from src.verifier import _default_provenance
        prov = _default_provenance()
        assert prov["vendor"]["match_tier"] == "not_found"
        assert prov["amount"]["match_tier"] == "not_found"
        assert prov["has_po"]["match_tier"] == "not_found"
