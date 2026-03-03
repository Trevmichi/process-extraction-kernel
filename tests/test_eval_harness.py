"""
tests/test_eval_harness.py
Tests for the evaluation harness infrastructure (eval_runner.py).

These validate the eval tooling itself — loading, validation, mock dispatch,
field comparison, metrics computation, and evidence grounding — NOT the agent
routing (that's test_batch_smoke.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_runner import (
    _validate_gold_record,
    build_mock_dispatch,
    compare_fields,
    compute_metrics,
    load_expected,
    load_invoice_text,
)
from src.verifier import _normalize_text

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
EXPECTED_PATH = DATASETS_DIR / "expected.jsonl"


# ===========================================================================
# TestLoadExpected
# ===========================================================================

class TestLoadExpected:

    def test_load_expected_reads_all_records(self):
        """expected.jsonl should contain exactly 30 gold records."""
        records = load_expected(EXPECTED_PATH)
        assert len(records) == 30

    def test_load_expected_validates_schema(self):
        """Every record passes _validate_gold_record without error."""
        records = load_expected(EXPECTED_PATH)
        for rec in records:
            _validate_gold_record(rec)  # should not raise


# ===========================================================================
# TestGoldRecordValidation
# ===========================================================================

class TestGoldRecordValidation:

    def test_validate_rejects_missing_keys(self):
        """A record missing expected_status should raise ValueError."""
        bad = {
            "invoice_id": "INV-9999",
            "file": "inv_999.txt",
            "po_match": True,
            # "expected_status" is missing
            "expected_fields": {"vendor": "X", "amount": 1.0, "has_po": True},
            "mock_extraction": {
                "vendor": {"value": "X", "evidence": "X"},
                "amount": {"value": 1.0, "evidence": "1.0"},
                "has_po": {"value": True, "evidence": "PO: X"},
            },
            "tags": [],
        }
        with pytest.raises(ValueError, match="missing keys"):
            _validate_gold_record(bad)


# ===========================================================================
# TestMockDispatch
# ===========================================================================

class TestMockDispatch:

    def test_mock_dispatch_raises_on_no_id(self):
        """Prompt with no invoice ID should raise ValueError (fail-fast)."""
        records = load_expected(EXPECTED_PATH)
        mock = build_mock_dispatch(records)
        with pytest.raises(ValueError, match="no known invoice ID"):
            mock("Extract data from this document about office supplies.")


# ===========================================================================
# TestCompareFields
# ===========================================================================

class TestCompareFields:

    def test_compare_fields_vendor_normalization(self):
        """Vendor comparison should be case-insensitive with whitespace collapse."""
        result = compare_fields(
            {"vendor": "ACME  SUPPLY"},
            {"vendor": "Acme Supply"},
        )
        assert result["vendor"]["match"] is True

    def test_compare_fields_amount_tolerance(self):
        """Amount comparison should tolerate <= 0.01 difference."""
        result = compare_fields(
            {"amount": 835.45},
            {"amount": 835.449},
        )
        assert result["amount"]["match"] is True

        result2 = compare_fields(
            {"amount": 835.45},
            {"amount": 835.47},
        )
        assert result2["amount"]["match"] is False


# ===========================================================================
# TestEvidenceGrounding
# ===========================================================================

class TestEvidenceGrounding:

    def test_mock_extraction_evidence_is_substring_of_invoice(self):
        """Every mock_extraction evidence string must be a substring of its
        invoice text, using the same _normalize_text normalizer as the runtime
        verifier (src/verifier.py).
        """
        records = load_expected(EXPECTED_PATH)
        for rec in records:
            raw_text = load_invoice_text(DATASETS_DIR, rec["file"])
            norm_text = _normalize_text(raw_text)

            for field, extraction in rec["mock_extraction"].items():
                evidence = extraction.get("evidence", "")
                if not evidence.strip():
                    continue  # empty evidence is tested separately by verifier
                norm_evidence = _normalize_text(evidence)
                assert norm_evidence in norm_text, (
                    f"{rec['invoice_id']}.{field}: evidence not found in invoice text\n"
                    f"  evidence (normalized): {norm_evidence!r}\n"
                    f"  invoice (normalized):  {norm_text[:200]!r}..."
                )
