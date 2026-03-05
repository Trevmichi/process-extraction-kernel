"""
Baseline zero-diff validation for verifier modularization cutover (RFC 3, Phase 3C1).

Runs shadow comparison (legacy vs registry) across all test fixtures and gold
invoice dataset. Every case must produce zero-diff before cutover proceeds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verifier_shadow import run_verifier_shadow_comparison

# ---------------------------------------------------------------------------
# Test fixtures from test_verifier.py
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
    return {
        "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
        "amount": {"value": 250.00, "evidence": "Total: $250.00"},
        "has_po": {"value": True, "evidence": "PO: PO-1122"},
    }


# Pairs: (label, raw_text, extraction)
_UNIT_FIXTURES: list[tuple[str, str, dict]] = [
    ("all_valid", RAW_TEXT, _valid_extraction()),
    (
        "multi_amount_keyword_disambiguates",
        RAW_TEXT_MULTI_AMOUNT,
        {
            "vendor": {"value": "Enterprise Servers Inc", "evidence": "Vendor: Enterprise Servers Inc"},
            "amount": {"value": 45000.00, "evidence": "Total: $45,000.00"},
            "has_po": {"value": True, "evidence": "PO: PO-9988"},
        },
    ),
    (
        "has_po_false_null_evidence",
        RAW_TEXT,
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": False, "evidence": None},
        },
    ),
    (
        "has_po_false_empty_evidence",
        RAW_TEXT,
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": False, "evidence": ""},
        },
    ),
    (
        "whitespace_extra_spaces",
        "Invoice\nVendor:   Office   Supplies   Co\nTotal: $250.00\nPO: PO-1122",
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor:   Office   Supplies   Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "no_po_na",
        "Invoice\nVendor: Acme\nTotal: $100.00\nPO: N/A",
        {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": False, "evidence": "PO: N/A"},
        },
    ),
    (
        "purchase_order_text",
        "Invoice\nVendor: Acme\nTotal: $100.00\nPurchase Order: 4567",
        {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Purchase Order: 4567"},
        },
    ),
    (
        "currency_dollar_commas",
        "Invoice\nVendor: Test Corp\nTotal: $1,234.56\nPO: PO-99",
        {
            "vendor": {"value": "Test Corp", "evidence": "Vendor: Test Corp"},
            "amount": {"value": 1234.56, "evidence": "Total: $1,234.56"},
            "has_po": {"value": True, "evidence": "PO: PO-99"},
        },
    ),
    (
        "currency_euro",
        "Invoice\nVendor: Test Corp\nTotal: €500.00\nPO: PO-99",
        {
            "vendor": {"value": "Test Corp", "evidence": "Vendor: Test Corp"},
            "amount": {"value": 500.00, "evidence": "Total: €500.00"},
            "has_po": {"value": True, "evidence": "PO: PO-99"},
        },
    ),
]

# Also include some failure-path fixtures to confirm both paths produce same failures
_FAILURE_FIXTURES: list[tuple[str, str, dict]] = [
    (
        "vendor_evidence_not_in_text",
        RAW_TEXT,
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Totally Fake Corp"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "empty_evidence_vendor",
        RAW_TEXT,
        {
            "vendor": {"value": "Office Supplies Co", "evidence": ""},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "amount_mismatch",
        RAW_TEXT,
        {
            "vendor": {"value": "Office Supplies Co", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 100.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "missing_vendor_value",
        RAW_TEXT,
        {
            "vendor": {"value": "", "evidence": "Vendor: Office Supplies Co"},
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "po_pattern_missing",
        "Invoice\nVendor: Acme\nTotal: $100.00\nNotes: None",
        {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.00, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "Notes: None"},
        },
    ),
    (
        "missing_key_vendor",
        RAW_TEXT,
        {
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "wrong_type_vendor_not_dict",
        RAW_TEXT,
        {
            "vendor": "Office Supplies Co",
            "amount": {"value": 250.00, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        },
    ),
    (
        "empty_extraction",
        RAW_TEXT,
        {},
    ),
]


ALL_UNIT_FIXTURES = _UNIT_FIXTURES + _FAILURE_FIXTURES


@pytest.mark.parametrize(
    "label,raw_text,extraction",
    [(f[0], f[1], f[2]) for f in ALL_UNIT_FIXTURES],
    ids=[f[0] for f in ALL_UNIT_FIXTURES],
)
def test_shadow_zero_diff_unit_fixtures(label: str, raw_text: str, extraction: dict):
    """Legacy and registry paths must produce identical results for unit fixtures."""
    report = run_verifier_shadow_comparison(raw_text, extraction)
    diff = report["diff"]
    assert diff["has_diff"] is False, (
        f"Shadow diff detected for fixture '{label}':\n"
        f"  valid_match={diff['valid_match']}, codes_match={diff['codes_match']}\n"
        f"  codes_only_legacy={diff['codes_only_in_legacy']}\n"
        f"  codes_only_registry={diff['codes_only_in_registry']}\n"
        f"  prov_mismatches={diff['provenance_value_mismatches']}\n"
        f"  notes={diff['notes']}"
    )


# ---------------------------------------------------------------------------
# Gold invoice dataset
# ---------------------------------------------------------------------------

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
GOLD_DIR = DATASETS_DIR / "gold_invoices"
EXPECTED_JSONL = DATASETS_DIR / "expected.jsonl"


def _load_gold_pairs() -> list[tuple[str, str, dict]]:
    """Load (invoice_id, raw_text, mock_extraction) from gold dataset."""
    pairs = []
    if not EXPECTED_JSONL.exists():
        return pairs
    for line in EXPECTED_JSONL.read_text(encoding="utf-8").strip().splitlines():
        rec = json.loads(line)
        invoice_file = GOLD_DIR / rec["file"]
        if not invoice_file.exists():
            continue
        raw_text = invoice_file.read_text(encoding="utf-8")
        extraction = rec.get("mock_extraction")
        if extraction is None:
            continue
        pairs.append((rec["invoice_id"], raw_text, extraction))
    return pairs


_GOLD_PAIRS = _load_gold_pairs()


@pytest.mark.parametrize(
    "invoice_id,raw_text,extraction",
    _GOLD_PAIRS,
    ids=[p[0] for p in _GOLD_PAIRS],
)
def test_shadow_zero_diff_gold_invoices(invoice_id: str, raw_text: str, extraction: dict):
    """Legacy and registry paths must produce identical results for gold invoices."""
    report = run_verifier_shadow_comparison(raw_text, extraction)
    diff = report["diff"]
    assert diff["has_diff"] is False, (
        f"Shadow diff detected for gold invoice '{invoice_id}':\n"
        f"  valid_match={diff['valid_match']}, codes_match={diff['codes_match']}\n"
        f"  codes_only_legacy={diff['codes_only_in_legacy']}\n"
        f"  codes_only_registry={diff['codes_only_in_registry']}\n"
        f"  prov_mismatches={diff['provenance_value_mismatches']}\n"
        f"  notes={diff['notes']}"
    )
