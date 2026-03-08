"""
tests/test_contracts.py
Shape validation tests for extraction and provenance contracts.

Verifies that runtime outputs from the verifier match the TypedDict
shapes defined in src/contracts.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.contracts import (
    AmountProvenance,
    ExtractionPayload,
    HasPoProvenance,
    InvoiceDateProvenance,
    ProvenanceReport,
    TaxAmountProvenance,
    VendorProvenance,
    validate_extraction_semantics,
    validate_extraction_structure,
)
from src.verifier import _default_provenance, verify_extraction


# ---------------------------------------------------------------------------
# Helper: check dict matches TypedDict keys
# ---------------------------------------------------------------------------

def _assert_keys_match(actual: dict, typed_dict_class, *, label: str = "") -> None:
    """Assert that actual dict has at least the required keys of a TypedDict."""
    # For total=True TypedDicts, __required_keys__ has all keys
    # For total=False, __required_keys__ may be empty
    required = getattr(typed_dict_class, "__required_keys__", set())
    annotations = typed_dict_class.__annotations__
    prefix = f"{label}: " if label else ""

    missing = required - set(actual.keys())
    assert not missing, f"{prefix}missing required keys: {sorted(missing)}"

    # All keys present should be declared in annotations
    extra = set(actual.keys()) - set(annotations.keys())
    assert not extra, f"{prefix}unexpected keys: {sorted(extra)}"


# ---------------------------------------------------------------------------
# _default_provenance() shape
# ---------------------------------------------------------------------------

class TestDefaultProvenance:
    """Verify _default_provenance() matches ProvenanceReport shape."""

    def test_has_required_top_level_keys(self) -> None:
        prov = _default_provenance()
        assert "vendor" in prov
        assert "amount" in prov
        assert "has_po" in prov

    def test_vendor_shape(self) -> None:
        prov = _default_provenance()
        _assert_keys_match(prov["vendor"], VendorProvenance, label="vendor")

    def test_amount_shape(self) -> None:
        prov = _default_provenance()
        _assert_keys_match(prov["amount"], AmountProvenance, label="amount")

    def test_has_po_shape(self) -> None:
        prov = _default_provenance()
        _assert_keys_match(prov["has_po"], HasPoProvenance, label="has_po")


# ---------------------------------------------------------------------------
# verify_extraction() provenance output shape
# ---------------------------------------------------------------------------

class TestVerifyExtractionProvenance:
    """Verify that verify_extraction() returns well-shaped provenance."""

    SAMPLE_RAW = "INVOICE #100\nVendor: Acme Corp\nTotal: $500.00\nPO: PO-1234"

    SAMPLE_EXTRACTION = {
        "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
        "amount": {"value": 500.00, "evidence": "Total: $500.00"},
        "has_po": {"value": True, "evidence": "PO: PO-1234"},
    }

    def test_provenance_has_core_fields(self) -> None:
        _valid, _codes, prov = verify_extraction(self.SAMPLE_RAW, self.SAMPLE_EXTRACTION)
        assert "vendor" in prov
        assert "amount" in prov
        assert "has_po" in prov

    def test_vendor_provenance_grounded(self) -> None:
        _valid, _codes, prov = verify_extraction(self.SAMPLE_RAW, self.SAMPLE_EXTRACTION)
        assert prov["vendor"]["grounded"] is True
        assert prov["vendor"]["evidence_found_at"] >= 0

    def test_amount_provenance_grounded(self) -> None:
        _valid, _codes, prov = verify_extraction(self.SAMPLE_RAW, self.SAMPLE_EXTRACTION)
        assert prov["amount"]["grounded"] is True

    def test_has_po_provenance_grounded(self) -> None:
        _valid, _codes, prov = verify_extraction(self.SAMPLE_RAW, self.SAMPLE_EXTRACTION)
        assert prov["has_po"]["grounded"] is True

    def test_optional_invoice_date_provenance_shape(self) -> None:
        extraction = {
            **self.SAMPLE_EXTRACTION,
            "invoice_date": {"value": "2024-01-15", "evidence": "Date: January 15, 2024"},
        }
        raw = self.SAMPLE_RAW + "\nDate: January 15, 2024"
        _valid, _codes, prov = verify_extraction(raw, extraction)
        assert "invoice_date" in prov
        _assert_keys_match(
            prov["invoice_date"], InvoiceDateProvenance, label="invoice_date"
        )

    def test_optional_tax_amount_provenance_shape(self) -> None:
        extraction = {
            **self.SAMPLE_EXTRACTION,
            "tax_amount": {"value": 50.00, "evidence": "Tax: $50.00"},
        }
        raw = self.SAMPLE_RAW + "\nTax: $50.00"
        _valid, _codes, prov = verify_extraction(raw, extraction)
        assert "tax_amount" in prov
        _assert_keys_match(
            prov["tax_amount"], TaxAmountProvenance, label="tax_amount"
        )


# ---------------------------------------------------------------------------
# ExtractionPayload shape: mock extraction from gold dataset
# ---------------------------------------------------------------------------

class TestExtractionPayloadShape:
    """Verify mock extractions match ExtractionPayload structure."""

    def test_minimal_extraction_has_required_fields(self) -> None:
        payload = {
            "vendor": {"value": "Test", "evidence": "Vendor: Test"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1"},
        }
        annotations = ExtractionPayload.__annotations__
        for field in ("vendor", "amount", "has_po"):
            assert field in payload
            assert field in annotations

    def test_error_payload_shape(self) -> None:
        """_error key should be valid in ExtractionPayload."""
        payload = {"_error": "LLM timeout"}
        assert "_error" in ExtractionPayload.__annotations__
        assert "_error" in payload


# ---------------------------------------------------------------------------
# validate_extraction_structure() — unit tests
# ---------------------------------------------------------------------------

_VALID_EXTRACTION = {
    "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
    "amount": {"value": 500.0, "evidence": "Total: $500.00"},
    "has_po": {"value": True, "evidence": "PO: PO-1234"},
}


class TestValidateExtractionStructure:
    """Unit tests for structural validation of LLM extraction output."""

    def test_valid_minimal(self) -> None:
        ok, issues = validate_extraction_structure(_VALID_EXTRACTION)
        assert ok is True
        assert issues == []

    def test_valid_with_extras(self) -> None:
        payload = {
            **_VALID_EXTRACTION,
            "invoice_date": {"value": "2024-01-15", "evidence": "Date: Jan 15"},
            "unknown_field": {"value": "x", "evidence": "y"},
        }
        ok, issues = validate_extraction_structure(payload)
        assert ok is True
        assert issues == []

    def test_error_payload(self) -> None:
        ok, issues = validate_extraction_structure({"_error": "timeout"})
        assert ok is False
        assert issues == ["STRUCT_LLM_ERROR"]

    def test_missing_vendor(self) -> None:
        payload = {k: v for k, v in _VALID_EXTRACTION.items() if k != "vendor"}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_MISSING_VENDOR" in issues

    def test_missing_amount(self) -> None:
        payload = {k: v for k, v in _VALID_EXTRACTION.items() if k != "amount"}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_MISSING_AMOUNT" in issues

    def test_missing_has_po(self) -> None:
        payload = {k: v for k, v in _VALID_EXTRACTION.items() if k != "has_po"}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_MISSING_HAS_PO" in issues

    def test_vendor_not_dict(self) -> None:
        payload = {**_VALID_EXTRACTION, "vendor": "Acme Corp"}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_NOT_DICT_VENDOR" in issues

    def test_missing_value_key(self) -> None:
        payload = {**_VALID_EXTRACTION, "vendor": {"evidence": "Vendor: Acme"}}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_NO_VALUE_VENDOR" in issues

    def test_missing_evidence_key(self) -> None:
        payload = {**_VALID_EXTRACTION, "amount": {"value": 100}}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_NO_EVIDENCE_AMOUNT" in issues

    def test_empty_dict(self) -> None:
        ok, issues = validate_extraction_structure({})
        assert ok is False
        assert len(issues) == 3
        assert "STRUCT_MISSING_VENDOR" in issues
        assert "STRUCT_MISSING_AMOUNT" in issues
        assert "STRUCT_MISSING_HAS_PO" in issues

    def test_multiple_issues(self) -> None:
        payload = {"has_po": {"value": True, "evidence": "PO: PO-1"}, "amount": "100"}
        ok, issues = validate_extraction_structure(payload)
        assert ok is False
        assert "STRUCT_MISSING_VENDOR" in issues
        assert "STRUCT_NOT_DICT_AMOUNT" in issues


# ---------------------------------------------------------------------------
# Provenance contracts — pipeline-level shape tests
# ---------------------------------------------------------------------------

class TestProvenanceContracts:
    """Verify provenance shape under different verification outcomes."""

    SAMPLE_RAW = "INVOICE #100\nVendor: Acme Corp\nTotal: $500.00\nPO: PO-1234"

    def test_successful_extraction_all_grounded(self) -> None:
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.0, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        valid, codes, prov = verify_extraction(self.SAMPLE_RAW, extraction)
        assert valid is True
        assert prov["vendor"]["grounded"] is True
        assert prov["amount"]["grounded"] is True
        assert prov["has_po"]["grounded"] is True

    def test_failed_evidence_shows_grounded_false(self) -> None:
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: FABRICATED"},
            "amount": {"value": 500.0, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        valid, codes, prov = verify_extraction(self.SAMPLE_RAW, extraction)
        assert valid is False
        assert prov["vendor"]["grounded"] is False

    def test_failure_codes_are_valid_literals(self) -> None:
        from src.verifier import FailureCode
        valid_codes = set(FailureCode.__args__)
        extraction = {
            "vendor": {"value": "", "evidence": ""},
            "amount": {"value": 999.0, "evidence": "nonexistent"},
            "has_po": {"value": True, "evidence": "nonexistent"},
        }
        _valid, codes, _prov = verify_extraction(self.SAMPLE_RAW, extraction)
        assert len(codes) > 0
        for code in codes:
            assert code in valid_codes, f"Unknown FailureCode: {code!r}"

    def test_optional_invoice_date_present(self) -> None:
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.0, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
            "invoice_date": {"value": "2024-01-15", "evidence": "Date: 01/15/2024"},
        }
        raw = self.SAMPLE_RAW + "\nDate: 01/15/2024"
        _valid, _codes, prov = verify_extraction(raw, extraction)
        assert "invoice_date" in prov

    def test_optional_invoice_date_absent(self) -> None:
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.0, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        _valid, _codes, prov = verify_extraction(self.SAMPLE_RAW, extraction)
        assert "invoice_date" not in prov

    def test_optional_tax_amount_present(self) -> None:
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Vendor: Acme Corp"},
            "amount": {"value": 500.0, "evidence": "Total: $500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
            "tax_amount": {"value": 50.0, "evidence": "Tax: $50.00"},
        }
        raw = self.SAMPLE_RAW + "\nTax: $50.00"
        _valid, _codes, prov = verify_extraction(raw, extraction)
        assert "tax_amount" in prov


# ---------------------------------------------------------------------------
# Semantic validation (SEM_* codes)
# ---------------------------------------------------------------------------

def _make_extraction(*, vendor="Acme Corp", amount=500.0, has_po=True):
    """Build a valid extraction payload for semantic tests."""
    return {
        "vendor": {"value": vendor, "evidence": "Vendor: Acme Corp"},
        "amount": {"value": amount, "evidence": "Total: $500.00"},
        "has_po": {"value": has_po, "evidence": "PO: PO-1234"},
    }


class TestValidateExtractionSemantics:
    """Unit tests for validate_extraction_semantics()."""

    def test_valid_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction())
        assert ok is True
        assert issues == []

    # --- vendor ---
    def test_vendor_empty(self):
        ok, issues = validate_extraction_semantics(_make_extraction(vendor=""))
        assert not ok
        assert "SEM_VENDOR_EMPTY" in issues

    def test_vendor_whitespace(self):
        ok, issues = validate_extraction_semantics(_make_extraction(vendor="   "))
        assert not ok
        assert "SEM_VENDOR_EMPTY" in issues

    def test_vendor_none_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction(vendor=None))
        assert ok is True

    # --- amount ---
    def test_amount_string(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount="abc"))
        assert not ok
        assert "SEM_AMOUNT_NOT_NUMERIC" in issues

    def test_amount_bool(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount=True))
        assert not ok
        assert "SEM_AMOUNT_NOT_NUMERIC" in issues

    def test_amount_negative(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount=-5.0))
        assert not ok
        assert "SEM_AMOUNT_NEGATIVE" in issues

    def test_amount_zero_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount=0))
        assert ok is True

    def test_amount_none_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount=None))
        assert ok is True

    def test_amount_int_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction(amount=100))
        assert ok is True

    # --- has_po ---
    def test_has_po_string(self):
        ok, issues = validate_extraction_semantics(_make_extraction(has_po="true"))
        assert not ok
        assert "SEM_HAS_PO_NOT_BOOL" in issues

    def test_has_po_int(self):
        ok, issues = validate_extraction_semantics(_make_extraction(has_po=1))
        assert not ok
        assert "SEM_HAS_PO_NOT_BOOL" in issues

    def test_has_po_none_passes(self):
        ok, issues = validate_extraction_semantics(_make_extraction(has_po=None))
        assert ok is True

    # --- multiple issues ---
    def test_multiple_issues(self):
        ok, issues = validate_extraction_semantics(
            _make_extraction(vendor="", amount="bad", has_po=1)
        )
        assert not ok
        assert len(issues) == 3
        assert "SEM_VENDOR_EMPTY" in issues
        assert "SEM_AMOUNT_NOT_NUMERIC" in issues
        assert "SEM_HAS_PO_NOT_BOOL" in issues

    # --- all codes are SEM_* prefixed ---
    def test_all_codes_prefixed(self):
        """Every code returned by semantic validation starts with SEM_."""
        payloads = [
            _make_extraction(vendor=""),
            _make_extraction(amount="x"),
            _make_extraction(amount=-1),
            _make_extraction(has_po=0),
        ]
        for p in payloads:
            _, issues = validate_extraction_semantics(p)
            for code in issues:
                assert code.startswith("SEM_"), f"Code {code!r} missing SEM_ prefix"
