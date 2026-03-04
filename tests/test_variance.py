"""
tests/test_variance.py
Unit tests for eval_variance.py — variance (fragility) scoring.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_variance import _flatten_extraction, run_variance_test


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gold_record(
    vendor: str = "Acme Corp",
    amount: float = 500.0,
    has_po: bool = True,
) -> dict:
    return {
        "expected_fields": {
            "vendor": vendor,
            "amount": amount,
            "has_po": has_po,
        }
    }


def _good_extraction(
    vendor: str = "Acme Corp",
    amount: float = 500.0,
    has_po: bool = True,
) -> dict:
    return {
        "vendor": {"value": vendor, "evidence": vendor},
        "amount": {"value": amount, "evidence": f"Total: {amount:.2f}"},
        "has_po": {"value": has_po, "evidence": "PO: 1234"},
    }


def _bad_extraction(bad_vendor: str = "Wrong Inc") -> dict:
    return {
        "vendor": {"value": bad_vendor, "evidence": bad_vendor},
        "amount": {"value": 500.0, "evidence": "Total: 500.00"},
        "has_po": {"value": True, "evidence": "PO: 1234"},
    }


def _error_extraction() -> dict:
    return {"_error": "LLM timeout"}


# ===========================================================================
# TestFlattenExtraction
# ===========================================================================

class TestFlattenExtraction:

    def test_normal(self):
        parsed = _good_extraction()
        flat = _flatten_extraction(parsed)
        assert flat == {"vendor": "Acme Corp", "amount": 500.0, "has_po": True}

    def test_missing_field(self):
        parsed = {"vendor": {"value": "X", "evidence": "X"}}
        flat = _flatten_extraction(parsed)
        assert flat["vendor"] == "X"
        assert flat["amount"] is None
        assert flat["has_po"] is None

    def test_malformed_entry(self):
        """Non-dict field entry maps to None."""
        parsed = {
            "vendor": "just a string",
            "amount": {"value": 100.0, "evidence": "100"},
            "has_po": 42,
        }
        flat = _flatten_extraction(parsed)
        assert flat["vendor"] is None
        assert flat["amount"] == 100.0
        assert flat["has_po"] is None


# ===========================================================================
# TestRunVarianceTest
# ===========================================================================

class TestRunVarianceTest:

    @patch("eval_variance._call_llm_json")
    def test_all_match_perfect_score(self, mock_llm):
        """5 identical correct extractions → fragility_score = 1.0."""
        mock_llm.return_value = _good_extraction()
        result = run_variance_test("INV-001", "dummy text", _gold_record(), runs=5)

        assert result["invoice_id"] == "INV-001"
        assert result["runs"] == 5
        assert result["matches"] == 5
        assert result["fragility_score"] == 1.0
        assert result["unstable_fields"] == []
        assert len(result["per_run"]) == 5

    @patch("eval_variance._call_llm_json")
    def test_mixed_results_fragility(self, mock_llm):
        """3 good + 2 bad vendor → score 0.6, vendor unstable."""
        mock_llm.side_effect = [
            _good_extraction(),
            _good_extraction(),
            _good_extraction(),
            _bad_extraction("Wrong Inc"),
            _bad_extraction("Wrong Inc"),
        ]
        result = run_variance_test("INV-002", "dummy text", _gold_record(), runs=5)

        assert result["matches"] == 3
        assert result["fragility_score"] == pytest.approx(0.6)
        assert "vendor" in result["unstable_fields"]
        assert "amount" not in result["unstable_fields"]
        assert "has_po" not in result["unstable_fields"]

    @patch("eval_variance._call_llm_json")
    def test_all_failures_zero_score(self, mock_llm):
        """All LLM errors → score 0.0, all fields unstable."""
        mock_llm.return_value = _error_extraction()
        result = run_variance_test("INV-003", "dummy text", _gold_record(), runs=5)

        assert result["matches"] == 0
        assert result["fragility_score"] == 0.0
        assert set(result["unstable_fields"]) == {"vendor", "amount", "has_po"}

    @patch("eval_variance._call_llm_json")
    def test_per_run_structure(self, mock_llm):
        """Each per_run entry has expected keys."""
        mock_llm.return_value = _good_extraction()
        result = run_variance_test("INV-004", "text", _gold_record(), runs=3)

        assert len(result["per_run"]) == 3
        for entry in result["per_run"]:
            assert "run" in entry
            assert "all_match" in entry
            assert "comparison" in entry

    @patch("eval_variance._call_llm_json")
    def test_single_run(self, mock_llm):
        """runs=1 works correctly."""
        mock_llm.return_value = _good_extraction()
        result = run_variance_test("INV-005", "text", _gold_record(), runs=1)

        assert result["runs"] == 1
        assert result["matches"] == 1
        assert result["fragility_score"] == 1.0

    @patch("eval_variance._call_llm_json")
    def test_llm_error_mid_run(self, mock_llm):
        """1 error among 4 good → score 0.8, all fields unstable from the error run."""
        mock_llm.side_effect = [
            _good_extraction(),
            _good_extraction(),
            _error_extraction(),
            _good_extraction(),
            _good_extraction(),
        ]
        result = run_variance_test("INV-006", "text", _gold_record(), runs=5)

        assert result["matches"] == 4
        assert result["fragility_score"] == pytest.approx(0.8)
        # The error run missed all fields
        assert set(result["unstable_fields"]) == {"vendor", "amount", "has_po"}

    @patch("eval_variance._call_llm_json")
    def test_fragility_score_zero_runs(self, mock_llm):
        """runs=0 edge case → no crash, score 0.0."""
        result = run_variance_test("INV-007", "text", _gold_record(), runs=0)

        assert result["runs"] == 0
        assert result["matches"] == 0
        assert result["fragility_score"] == 0.0
        assert result["per_run"] == []
        mock_llm.assert_not_called()

    @patch("eval_variance._call_llm_json")
    def test_partial_field_mismatch(self, mock_llm):
        """Amount wrong on 2 runs → amount is unstable, overall match fails on those."""
        bad_amount = _good_extraction()
        bad_amount["amount"] = {"value": 999.99, "evidence": "Total: 999.99"}

        mock_llm.side_effect = [
            _good_extraction(),
            bad_amount,
            _good_extraction(),
            bad_amount,
            _good_extraction(),
        ]
        result = run_variance_test("INV-008", "text", _gold_record(), runs=5)

        assert result["matches"] == 3
        assert result["fragility_score"] == pytest.approx(0.6)
        assert "amount" in result["unstable_fields"]
        assert "vendor" not in result["unstable_fields"]
