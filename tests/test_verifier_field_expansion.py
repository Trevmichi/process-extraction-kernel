"""
Tests for RFC 6B: invoice_date and tax_amount verifier field expansion.

Covers date disambiguation, tax anchoring, edge cases, backward compatibility,
and shadow registry agreement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verifier import verify_extraction
from src.verifier_shadow import run_verifier_shadow_comparison

RAW_TEXT = (
    "Delta Mechanical Services\n"
    "890 Industrial Pkwy, Detroit, MI 48201\n"
    "\n"
    "Date: 12/31/2025\n"
    "Invoice Number: INV-9001\n"
    "PO Number: PO-DMS-100\n"
    "\n"
    "Subtotal: 200.00\n"
    "Shipping: 15.00\n"
    "Tax: 35.00\n"
    "Total Due: 250.00\n"
)


def _base_extraction(**overrides):
    ext = {
        "vendor": {"value": "Delta Mechanical Services", "evidence": "Delta Mechanical Services"},
        "amount": {"value": 250.00, "evidence": "Total Due: 250.00"},
        "has_po": {"value": True, "evidence": "PO Number: PO-DMS-100"},
    }
    ext.update(overrides)
    return ext


def test_invoice_date_us_format_normalizes_to_iso():
    extraction = _base_extraction(
        invoice_date={"value": "2025-12-31", "evidence": "Date: 12/31/2025"},
    )
    valid, codes, prov = verify_extraction(RAW_TEXT, extraction)
    assert "DATE_AMBIGUOUS" not in codes
    assert "DATE_PARSE_FAILED" not in codes
    assert prov["invoice_date"]["normalized_value"] == "2025-12-31"
    assert prov["invoice_date"]["normalized_evidence"] == "2025-12-31"


def test_invoice_date_eu_format_unambiguous():
    raw = (
        "Global Logistics Corp\n"
        "Industriestrasse 45, Munich\n"
        "Invoice Date: 31/12/2025\n"
        "PO Number: PO-GLC-1\n"
        "Total: 100.00\n"
    )
    extraction = {
        "vendor": {"value": "Global Logistics Corp", "evidence": "Global Logistics Corp"},
        "amount": {"value": 100.00, "evidence": "Total: 100.00"},
        "has_po": {"value": True, "evidence": "PO Number: PO-GLC-1"},
        "invoice_date": {"value": "2025-12-31", "evidence": "Invoice Date: 31/12/2025"},
    }
    valid, codes, prov = verify_extraction(raw, extraction)
    assert "DATE_AMBIGUOUS" not in codes
    assert prov["invoice_date"]["normalized_value"] == "2025-12-31"


def test_invoice_date_iso_format():
    raw = (
        "Vendor Co\nDate: 2025-12-31\nPO Number: PO-1\nTotal: 50.00\n"
    )
    extraction = {
        "vendor": {"value": "Vendor Co", "evidence": "Vendor Co"},
        "amount": {"value": 50.00, "evidence": "Total: 50.00"},
        "has_po": {"value": True, "evidence": "PO Number: PO-1"},
        "invoice_date": {"value": "2025-12-31", "evidence": "Date: 2025-12-31"},
    }
    valid, codes, prov = verify_extraction(raw, extraction)
    assert "DATE_PARSE_FAILED" not in codes
    assert prov["invoice_date"]["normalized_value"] == "2025-12-31"


def test_invoice_date_ambiguous_fails_explicitly():
    raw = (
        "Vendor Co\nDate: 03/04/2025\nPO Number: PO-1\nTotal: 50.00\n"
    )
    extraction = {
        "vendor": {"value": "Vendor Co", "evidence": "Vendor Co"},
        "amount": {"value": 50.00, "evidence": "Total: 50.00"},
        "has_po": {"value": True, "evidence": "PO Number: PO-1"},
        "invoice_date": {"value": "2025-03-04", "evidence": "Date: 03/04/2025"},
    }
    valid, codes, prov = verify_extraction(raw, extraction)
    assert valid is False
    assert "DATE_AMBIGUOUS" in codes


def test_tax_anchor_disambiguates_from_subtotal_shipping_total():
    extraction = _base_extraction(
        tax_amount={"value": 35.00, "evidence": "Tax: 35.00"},
    )
    valid, codes, prov = verify_extraction(RAW_TEXT, extraction)
    assert "TAX_AMBIGUOUS_EVIDENCE" not in codes
    assert "TAX_ANCHOR_MISSING" not in codes
    assert prov["tax_amount"]["parsed_evidence"] == 35.0


def test_tax_zero_line_is_valid():
    raw = (
        "Vendor Co\nPO Number: PO-1\nSubtotal: 100.00\nTax: 0.00\nTotal: 100.00\n"
    )
    extraction = {
        "vendor": {"value": "Vendor Co", "evidence": "Vendor Co"},
        "amount": {"value": 100.00, "evidence": "Total: 100.00"},
        "has_po": {"value": True, "evidence": "PO Number: PO-1"},
        "tax_amount": {"value": 0.00, "evidence": "Tax: 0.00"},
    }
    valid, codes, prov = verify_extraction(raw, extraction)
    assert "TAX_AMOUNT_MISMATCH" not in codes
    assert prov["tax_amount"]["parsed_evidence"] == 0.0


def test_invoice_date_wrong_type():
    extraction = _base_extraction(
        invoice_date={"value": 20251231, "evidence": "Date: 12/31/2025"},
    )
    valid, codes, prov = verify_extraction(RAW_TEXT, extraction)
    assert valid is False
    assert "DATE_WRONG_TYPE" in codes


def test_tax_missing_key_and_evidence_not_found_cases():
    # Part A: missing evidence key
    extraction_a = _base_extraction(
        tax_amount={"value": 35.00},
    )
    valid_a, codes_a, _ = verify_extraction(RAW_TEXT, extraction_a)
    assert "TAX_MISSING_KEY" in codes_a

    # Part B: evidence not in raw text
    extraction_b = _base_extraction(
        tax_amount={"value": 9.99, "evidence": "Tax: 9.99"},
    )
    valid_b, codes_b, _ = verify_extraction(RAW_TEXT, extraction_b)
    assert "TAX_EVIDENCE_NOT_FOUND" in codes_b


def test_existing_fields_unchanged_when_new_fields_absent():
    extraction = _base_extraction()
    valid, codes, prov = verify_extraction(RAW_TEXT, extraction)
    assert valid is True
    assert set(prov.keys()) == {"vendor", "amount", "has_po"}


def test_shadow_registry_no_diff_with_expanded_fields():
    extraction = _base_extraction(
        invoice_date={"value": "2025-12-31", "evidence": "Date: 12/31/2025"},
        tax_amount={"value": 35.00, "evidence": "Tax: 35.00"},
    )
    report = run_verifier_shadow_comparison(RAW_TEXT, extraction)
    assert report["diff"]["has_diff"] is False
