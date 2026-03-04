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
    check_trace,
    classify_failure,
    compare_fields,
    compute_metrics,
    load_expected,
    load_invoice_text,
    should_exit_zero,
)
from src.verifier import _normalize_text

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
EXPECTED_PATH = DATASETS_DIR / "expected.jsonl"


# ===========================================================================
# TestLoadExpected
# ===========================================================================

class TestLoadExpected:

    def test_load_expected_reads_all_records(self):
        """expected.jsonl should contain exactly 50 gold records."""
        records = load_expected(EXPECTED_PATH)
        assert len(records) == 50

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


# ===========================================================================
# TestTagMetrics
# ===========================================================================

class TestTagMetrics:

    def test_by_tag_contains_expected_keys(self):
        """compute_metrics should produce by_tag with correct structure."""
        results = [
            {
                "invoice_id": "T-0001",
                "expected_status": ["APPROVED"],
                "actual_status": "APPROVED",
                "status_match": True,
                "field_comparison": {
                    "vendor": {"expected": "X", "actual": "X", "match": True},
                    "amount": {"expected": 100.0, "actual": 100.0, "match": True},
                },
                "match_result": "MATCH",
                "tags": ["happy_path", "vendor_x"],
                "audit_log": [],
                "failure_bucket": "pass",
                "field_mismatches": [],
            },
            {
                "invoice_id": "T-0002",
                "expected_status": ["EXCEPTION_NO_PO"],
                "actual_status": "EXCEPTION_NO_PO",
                "status_match": True,
                "field_comparison": {
                    "vendor": {"expected": "Y", "actual": "Y", "match": True},
                    "amount": {"expected": 50.0, "actual": 50.0, "match": True},
                },
                "match_result": "UNKNOWN",
                "tags": ["no_po", "vendor_x"],
                "audit_log": [],
                "failure_bucket": "pass",
                "field_mismatches": [],
            },
        ]
        metrics = compute_metrics(results)
        assert "by_tag" in metrics
        assert "happy_path" in metrics["by_tag"]
        assert "no_po" in metrics["by_tag"]
        assert "vendor_x" in metrics["by_tag"]

        hp = metrics["by_tag"]["happy_path"]
        assert hp["count"] == 1
        assert hp["terminal_accuracy"]["correct"] == 1
        assert hp["terminal_accuracy"]["accuracy"] == 1.0

        vx = metrics["by_tag"]["vendor_x"]
        assert vx["count"] == 2

    def test_by_tag_field_accuracy(self):
        """by_tag field accuracy should be computed per tag."""
        results = [
            {
                "invoice_id": "T-0001",
                "expected_status": ["APPROVED"],
                "actual_status": "APPROVED",
                "status_match": True,
                "field_comparison": {
                    "vendor": {"expected": "X", "actual": "Z", "match": False},
                    "amount": {"expected": 100.0, "actual": 100.0, "match": True},
                },
                "match_result": "MATCH",
                "tags": ["tag_a"],
                "audit_log": [],
                "failure_bucket": "field_mismatch",
                "field_mismatches": ["vendor"],
            },
        ]
        metrics = compute_metrics(results)
        tag_a = metrics["by_tag"]["tag_a"]
        assert tag_a["field_accuracy"]["vendor"]["correct"] == 0
        assert tag_a["field_accuracy"]["amount"]["correct"] == 1
        assert tag_a["field_accuracy"]["overall"]["correct"] == 1
        assert tag_a["field_accuracy"]["overall"]["total"] == 2


# ===========================================================================
# TestFailureBucketing
# ===========================================================================

class TestFailureBucketing:

    def test_pass(self):
        fc = {"vendor": {"match": True}, "amount": {"match": True}}
        result = classify_failure(True, fc)
        assert result["failure_bucket"] == "pass"
        assert result["field_mismatches"] == []

    def test_terminal_mismatch_only(self):
        fc = {"vendor": {"match": True}, "amount": {"match": True}}
        result = classify_failure(False, fc)
        assert result["failure_bucket"] == "terminal_mismatch"

    def test_field_mismatch_only(self):
        fc = {"vendor": {"match": False}, "amount": {"match": True}}
        result = classify_failure(True, fc)
        assert result["failure_bucket"] == "field_mismatch"
        assert result["field_mismatches"] == ["vendor"]

    def test_both_mismatch(self):
        fc = {"vendor": {"match": False}, "amount": {"match": False}}
        result = classify_failure(False, fc)
        assert result["failure_bucket"] == "both_terminal_and_field_mismatch"
        assert sorted(result["field_mismatches"]) == ["amount", "vendor"]


# ===========================================================================
# TestTraceChecks
# ===========================================================================

class TestTraceChecks:

    def test_must_include_route_decision(self):
        """Audit log with route_decision event should satisfy must_include."""
        import json as _json
        audit_log = [
            _json.dumps({"event": "route_decision", "from_node": "n3",
                         "selected": "n4", "reason": "condition_match"}),
        ]
        trace = {"must_include": ["route_decision"]}
        result = check_trace(audit_log, trace)
        assert result["must_include_passed"] is True
        assert result["missing"] == []

    def test_must_include_node_id(self):
        """Must_include with a node ID checks from_node/selected/node."""
        import json as _json
        audit_log = [
            _json.dumps({"event": "route_decision", "from_node": "n3",
                         "selected": "n4", "reason": "condition_match"}),
        ]
        result = check_trace(audit_log, {"must_include": ["n3"]})
        assert result["must_include_passed"] is True

        result2 = check_trace(audit_log, {"must_include": ["n_reject"]})
        assert result2["must_include_passed"] is False
        assert result2["missing"] == ["n_reject"]

    def test_must_exclude_fires(self):
        """Must_exclude should detect forbidden entries."""
        import json as _json
        audit_log = [
            _json.dumps({"event": "route_decision", "from_node": "n3",
                         "selected": "n_reject", "reason": "condition_match"}),
        ]
        result = check_trace(audit_log, {"must_exclude": ["n_reject"]})
        assert result["must_exclude_passed"] is False
        assert result["forbidden_found"] == ["n_reject"]

    def test_empty_audit_log(self):
        """Empty audit_log with must_include should fail cleanly."""
        result = check_trace([], {"must_include": ["route_decision"]})
        assert result["must_include_passed"] is False
        assert result["missing"] == ["route_decision"]
        assert result["must_exclude_passed"] is True

    def test_plain_text_entries_ignored(self):
        """Plain text audit entries should not crash parsing."""
        audit_log = ["Executed APPROVE at n6", "Validation result: ok"]
        result = check_trace(audit_log, {"must_include": ["route_decision"]})
        assert result["must_include_passed"] is False


# ===========================================================================
# TestExitCodeLogic
# ===========================================================================

class TestExitCodeLogic:

    def test_all_pass(self):
        """Both 100% terminal and field accuracy → exit zero."""
        m = {"terminal_accuracy": {"accuracy": 1.0},
             "field_accuracy": {"overall": {"accuracy": 1.0}}}
        assert should_exit_zero(m) is True

    def test_field_only_failure(self):
        """terminal=100%, field<100% → exit non-zero."""
        m = {"terminal_accuracy": {"accuracy": 1.0},
             "field_accuracy": {"overall": {"accuracy": 0.99}}}
        assert should_exit_zero(m) is False

    def test_terminal_only_failure(self):
        """terminal<100%, field=100% → exit non-zero."""
        m = {"terminal_accuracy": {"accuracy": 0.98},
             "field_accuracy": {"overall": {"accuracy": 1.0}}}
        assert should_exit_zero(m) is False
