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
    compute_failure_groupings,
    compute_metrics,
    load_expected,
    load_invoice_text,
    should_exit_zero,
)
from eval_audit import (
    build_diagnostic_snapshot,
    compute_signals,
    select_audit_targets,
    _validate_audit_result,
    _make_unclear_result,
    _extract_json,
    _parse_trace_summary,
    run_audit,
    VERDICTS,
    ROOT_CAUSE_CATEGORIES,
)
from src.verifier import _normalize_text

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
EXPECTED_PATH = DATASETS_DIR / "expected.jsonl"


# ===========================================================================
# TestLoadExpected
# ===========================================================================

class TestLoadExpected:

    def test_load_expected_reads_all_records(self):
        """expected.jsonl should contain at least 50 gold records."""
        records = load_expected(EXPECTED_PATH)
        assert len(records) >= 50

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
                evidence = extraction.get("evidence") or ""
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


# ===========================================================================
# TestFailureGroupings (Part B)
# ===========================================================================

def _make_result(invoice_id, bucket="pass", tags=None):
    """Helper to build a minimal per-invoice result dict."""
    return {
        "invoice_id": invoice_id,
        "failure_bucket": bucket,
        "tags": tags or [],
        "expected_status": ["APPROVED"],
        "actual_status": "APPROVED" if bucket == "pass" else "REJECTED",
        "status_match": bucket == "pass",
        "field_comparison": {},
        "match_result": "MATCH",
        "audit_log": [],
        "field_mismatches": [],
    }


class TestFailureGroupings:

    def test_failures_by_bucket_structure(self):
        """failures_by_bucket always has all 3 bucket keys (stable shape)."""
        results = [
            _make_result("INV-0001", "terminal_mismatch", ["tag_a"]),
            _make_result("INV-0002", "pass", ["tag_a"]),
        ]
        by_bucket, _ = compute_failure_groupings(results)
        assert set(by_bucket.keys()) == {
            "terminal_mismatch", "field_mismatch",
            "both_terminal_and_field_mismatch",
        }
        assert by_bucket["terminal_mismatch"] == ["INV-0001"]
        assert by_bucket["field_mismatch"] == []
        assert by_bucket["both_terminal_and_field_mismatch"] == []

    def test_failures_by_tag_only_failing_tags(self):
        """failures_by_tag only includes tags with ≥1 failure."""
        results = [
            _make_result("INV-0001", "field_mismatch", ["no_po"]),
            _make_result("INV-0002", "pass", ["happy_path"]),
        ]
        _, by_tag = compute_failure_groupings(results)
        assert "no_po" in by_tag
        assert "happy_path" not in by_tag
        assert by_tag["no_po"]["field_mismatch"] == ["INV-0001"]

    def test_empty_failures(self):
        """When all pass, buckets are empty but all keys present."""
        results = [
            _make_result("INV-0001", "pass", ["tag_a"]),
            _make_result("INV-0002", "pass", ["tag_b"]),
        ]
        by_bucket, by_tag = compute_failure_groupings(results)
        assert all(v == [] for v in by_bucket.values())
        assert by_tag == {}

    def test_multiple_tags_per_invoice(self):
        """A failing invoice with multiple tags appears in each tag's bucket."""
        results = [
            _make_result("INV-0001", "terminal_mismatch", ["no_po", "high_value"]),
        ]
        _, by_tag = compute_failure_groupings(results)
        assert "no_po" in by_tag
        assert "high_value" in by_tag
        assert by_tag["no_po"]["terminal_mismatch"] == ["INV-0001"]
        assert by_tag["high_value"]["terminal_mismatch"] == ["INV-0001"]


# ===========================================================================
# TestAuditTargetSelection
# ===========================================================================

class TestAuditTargetSelection:

    def _results(self):
        return [
            _make_result("INV-0001", "pass"),
            _make_result("INV-0002", "pass"),
            _make_result("INV-0003", "pass"),
            _make_result("INV-0004", "terminal_mismatch"),
            _make_result("INV-0005", "field_mismatch"),
        ]

    def test_failures_always_included(self):
        """In failures_and_sample mode, all failures are always included."""
        targets = select_audit_targets(
            self._results(), "failures_and_sample", audit_sample=1, audit_seed=42,
        )
        target_ids = [t["invoice_id"] for t in targets]
        assert "INV-0004" in target_ids
        assert "INV-0005" in target_ids

    def test_sample_size_respected(self):
        """Number of sampled passes should not exceed audit_sample."""
        targets = select_audit_targets(
            self._results(), "failures_and_sample", audit_sample=2, audit_seed=42,
        )
        pass_targets = [t for t in targets if t["failure_bucket"] == "pass"]
        assert len(pass_targets) <= 2

    def test_deterministic_seed(self):
        """Same seed produces same targets."""
        t1 = select_audit_targets(
            self._results(), "failures_and_sample", audit_sample=2, audit_seed=99,
        )
        t2 = select_audit_targets(
            self._results(), "failures_and_sample", audit_sample=2, audit_seed=99,
        )
        assert [t["invoice_id"] for t in t1] == [t["invoice_id"] for t in t2]

    def test_audit_mode_failures_only(self):
        """failures_only mode excludes all passes."""
        targets = select_audit_targets(
            self._results(), "failures_only", audit_sample=10, audit_seed=42,
        )
        assert all(t["failure_bucket"] != "pass" for t in targets)
        assert len(targets) == 2

    def test_audit_mode_sample_only(self):
        """sample_only mode excludes all failures."""
        targets = select_audit_targets(
            self._results(), "sample_only", audit_sample=2, audit_seed=42,
        )
        assert all(t["failure_bucket"] == "pass" for t in targets)
        assert len(targets) == 2

    def test_audit_max_caps_total(self):
        """audit_max trims from passes first."""
        targets = select_audit_targets(
            self._results(), "failures_and_sample", audit_sample=3,
            audit_seed=42, audit_max=3,
        )
        assert len(targets) <= 3
        # Failures (2) should still be included
        failure_ids = [t["invoice_id"] for t in targets
                       if t["failure_bucket"] != "pass"]
        assert len(failure_ids) == 2


# ===========================================================================
# TestDiagnosticSnapshot
# ===========================================================================

class TestDiagnosticSnapshot:

    def test_amount_candidates_extracted(self):
        """Amount candidates should find all money-like numbers."""
        raw = "Invoice Total: $1,250.00\nTax: $125.00\nSubtotal: $1,125.00"
        snapshot = build_diagnostic_snapshot(raw, {}, {"audit_log": []})
        assert len(snapshot["amount_candidates"]) >= 3
        assert 1250.0 in snapshot["amount_candidates"]
        assert 125.0 in snapshot["amount_candidates"]

    def test_po_candidates_extracted(self):
        """PO candidates should find PO-like patterns."""
        raw = "Reference: PO-12345\nVendor: ACME"
        snapshot = build_diagnostic_snapshot(raw, {}, {"audit_log": []})
        assert len(snapshot["po_candidates"]) >= 1
        # PO_RE matches 'PO' as a word boundary match
        assert any("PO" in c for c in snapshot["po_candidates"])

    def test_vendor_line_candidates(self):
        """Should return first 5 non-empty lines."""
        raw = "ACME Corp\n123 Main St\nCity, ST 12345\n\nInvoice #1001\nDate: 2024-01-01\nMore lines"
        snapshot = build_diagnostic_snapshot(raw, {}, {"audit_log": []})
        assert len(snapshot["vendor_line_candidates"]) == 5
        assert snapshot["vendor_line_candidates"][0] == "ACME Corp"

    def test_trace_summary_from_audit_log(self):
        """Trace summary should parse route_decision events."""
        import json as _json
        audit_log = [
            _json.dumps({"event": "route_decision", "from_node": "n3",
                         "selected": "n4", "reason": "condition_match"}),
            _json.dumps({"event": "verifier_summary", "valid": True,
                         "failure_codes": []}),
        ]
        snapshot = build_diagnostic_snapshot("text", {}, {"audit_log": audit_log})
        trace = snapshot["trace_summary"]
        assert len(trace["route_decisions"]) == 1
        assert trace["route_decisions"][0]["from_node"] == "n3"
        assert trace["verifier_summary"]["valid"] is True

    def test_empty_audit_log_safe(self):
        """Empty audit_log should produce safe defaults."""
        snapshot = build_diagnostic_snapshot("", {}, {"audit_log": []})
        trace = snapshot["trace_summary"]
        assert trace["route_decisions"] == []
        assert trace["verifier_summary"] is None
        assert trace["exception_station"] is None

    def test_total_line_candidates(self):
        """Should find lines with total/amount due keywords."""
        raw = "Item: Widget\nTotal: $500.00\nAmount Due: $500.00\nThank you"
        snapshot = build_diagnostic_snapshot(raw, {}, {"audit_log": []})
        assert len(snapshot["total_line_candidates"]) == 2


# ===========================================================================
# TestAuditSignals
# ===========================================================================

class TestAuditSignals:

    def test_multiple_totals_detected(self):
        """Signal should fire when >1 amount candidate found."""
        snapshot = {"amount_candidates": [100.0, 200.0], "po_candidates": []}
        signals = compute_signals(snapshot, {})
        assert signals["multiple_total_candidates"] is True

    def test_single_total_not_flagged(self):
        """Signal should not fire with exactly 1 amount candidate."""
        snapshot = {"amount_candidates": [100.0], "po_candidates": []}
        signals = compute_signals(snapshot, {})
        assert signals["multiple_total_candidates"] is False

    def test_po_mismatch_detected(self):
        """Signal should fire when gold says has_po=true but no PO regex match."""
        snapshot = {"amount_candidates": [], "po_candidates": []}
        gold = {"expected_fields": {"has_po": True}}
        signals = compute_signals(snapshot, gold)
        assert signals["po_missing_but_has_po_true"] is True

    def test_po_mismatch_not_flagged_when_po_found(self):
        """Signal should not fire when PO candidates exist."""
        snapshot = {"amount_candidates": [], "po_candidates": ["PO-12345"]}
        gold = {"expected_fields": {"has_po": True}}
        signals = compute_signals(snapshot, gold)
        assert signals["po_missing_but_has_po_true"] is False


# ===========================================================================
# TestAuditReportStructure
# ===========================================================================

class TestAuditReportStructure:

    def test_validate_audit_result_normalizes(self):
        """_validate_audit_result should normalize valid LLM responses."""
        raw = {
            "verdict": "deterministic_bug",
            "confidence": 0.85,
            "root_cause_category": "AMOUNT_DISAMBIGUATION",
            "explanation": "The amount was wrong.",
            "recommended_action": "Fix verifier.",
            "suggested_new_test_cases": [],
        }
        result = _validate_audit_result(raw)
        assert result["verdict"] == "deterministic_bug"
        assert result["confidence"] == 0.85
        assert result["root_cause_category"] == "AMOUNT_DISAMBIGUATION"

    def test_validate_audit_result_clamps_confidence(self):
        """Confidence should be clamped to [0, 1]."""
        raw = {"confidence": 1.5, "verdict": "unclear"}
        result = _validate_audit_result(raw)
        assert result["confidence"] == 1.0

        raw2 = {"confidence": -0.5, "verdict": "unclear"}
        result2 = _validate_audit_result(raw2)
        assert result2["confidence"] == 0.0

    def test_validate_audit_result_bad_verdict_becomes_unclear(self):
        """Unknown verdict should be replaced with 'unclear'."""
        raw = {"verdict": "totally_wrong", "root_cause_category": "INVALID"}
        result = _validate_audit_result(raw)
        assert result["verdict"] == "unclear"
        assert result["root_cause_category"] == "OTHER"

    def test_make_unclear_result_structure(self):
        """_make_unclear_result should produce well-formed dict."""
        result = _make_unclear_result("test reason")
        assert result["verdict"] == "unclear"
        assert result["confidence"] == 0.0
        assert result["explanation"] == "test reason"
        assert result["suggested_new_test_cases"] == []

    def test_extract_json_plain(self):
        """_extract_json should parse plain JSON."""
        raw = '{"verdict": "unclear"}'
        assert _extract_json(raw)["verdict"] == "unclear"

    def test_extract_json_fenced(self):
        """_extract_json should strip markdown fences."""
        raw = '```json\n{"verdict": "unclear"}\n```'
        assert _extract_json(raw)["verdict"] == "unclear"

    def test_extract_json_with_prefix(self):
        """_extract_json should find JSON even with surrounding text."""
        raw = 'Here is the result: {"verdict": "unclear"} done.'
        assert _extract_json(raw)["verdict"] == "unclear"

    def test_failed_llm_produces_unclear_verdict(self):
        """When audit_llm_call returns _error, verdict should be 'unclear'."""
        from unittest.mock import patch as mock_patch

        # Mock audit_llm_call to return error
        with mock_patch("eval_audit.audit_llm_call",
                        return_value={"_error": "connection refused"}):
            results = [_make_result("INV-0001", "terminal_mismatch")]
            gold = [{
                "invoice_id": "INV-0001",
                "file": "inv_0001.txt",
                "expected_status": ["APPROVED"],
                "expected_fields": {"vendor": "X", "amount": 100.0, "has_po": True},
            }]
            # Also mock the file read
            with mock_patch("eval_audit.Path.read_text", return_value="Invoice text"):
                audit = run_audit(
                    results, gold, Path("datasets"),
                    audit_mode="failures_only", audit_sample=0, audit_seed=42,
                )
        assert len(audit["audits"]) == 1
        assert audit["audits"][0]["llm_audit"]["verdict"] == "unclear"
        assert "connection refused" in audit["audits"][0]["llm_audit"]["explanation"]

    def test_audit_report_top_level_keys(self):
        """Audit report should have run, summary, audits keys."""
        from unittest.mock import patch as mock_patch

        mock_llm_response = {
            "verdict": "model_extraction_error",
            "confidence": 0.7,
            "root_cause_category": "AMOUNT_DISAMBIGUATION",
            "explanation": "Test",
            "recommended_action": "Fix",
            "suggested_new_test_cases": [],
        }
        with mock_patch("eval_audit.audit_llm_call",
                        return_value=mock_llm_response):
            results = [_make_result("INV-0001", "terminal_mismatch")]
            gold = [{
                "invoice_id": "INV-0001",
                "file": "inv_0001.txt",
                "expected_status": ["APPROVED"],
                "expected_fields": {},
            }]
            with mock_patch("eval_audit.Path.read_text", return_value="text"):
                audit = run_audit(
                    results, gold, Path("datasets"),
                    audit_mode="failures_only", audit_sample=0, audit_seed=42,
                )
        assert "run" in audit
        assert "summary" in audit
        assert "audits" in audit
        assert audit["run"]["audit_mode"] == "failures_only"
        assert audit["summary"]["audited_count"] == 1
        assert audit["summary"]["failures_audited"] == 1
        assert audit["summary"]["passes_audited"] == 0


# ===========================================================================
# TestTagConventions
# ===========================================================================

class TestTagConventions:
    """Validate all tags across expected.jsonl are lowercase snake_case."""

    def test_all_tags_are_lowercase_snake_case(self):
        """Every tag in expected.jsonl must match [a-z][a-z0-9_]* pattern."""
        import re
        tag_re = re.compile(r"^[a-z][a-z0-9_]*$")
        records = load_expected(EXPECTED_PATH)
        bad = []
        for rec in records:
            for tag in rec.get("tags", []):
                if not tag_re.match(tag):
                    bad.append((rec["invoice_id"], tag))
        assert bad == [], f"Non-snake_case tags found: {bad}"

    def test_no_empty_tags_list(self):
        """Every record should have at least one tag."""
        records = load_expected(EXPECTED_PATH)
        empty = [r["invoice_id"] for r in records if not r.get("tags")]
        assert empty == [], f"Records with no tags: {empty}"


# ===========================================================================
# TestAdversarialFixturePresence
# ===========================================================================

class TestAdversarialFixturePresence:
    """Assert all adversarial fixture files exist and are referenced."""

    ADVERSARIAL_FILES = [f"inv_{n:03d}.txt" for n in range(57, 69)]
    ADVERSARIAL_IDS = [f"INV-{n}" for n in range(1057, 1069)]

    def test_fixture_files_exist(self):
        """All adversarial invoice text files must exist on disk."""
        for fname in self.ADVERSARIAL_FILES:
            path = DATASETS_DIR / "gold_invoices" / fname
            assert path.exists(), f"Missing fixture: {path}"

    def test_fixture_ids_in_expected(self):
        """All adversarial invoice IDs must appear in expected.jsonl."""
        records = load_expected(EXPECTED_PATH)
        ids = {r["invoice_id"] for r in records}
        for inv_id in self.ADVERSARIAL_IDS:
            assert inv_id in ids, f"Missing from expected.jsonl: {inv_id}"

    def test_adversarial_tags_present(self):
        """Each adversarial scenario tag must appear in at least one record."""
        required_tags = {
            "threshold_edge_exact", "po_false_positive_prose",
            "duplicate_total_lines", "ocr_spacing",
            "vendor_alias_variation", "footer_total_vs_amount_due_conflict",
            "multi_currency_symbol_noise",
        }
        records = load_expected(EXPECTED_PATH)
        all_tags = set()
        for r in records:
            all_tags.update(r.get("tags", []))
        missing = required_tags - all_tags
        assert missing == set(), f"Missing adversarial tags: {missing}"


# ===========================================================================
# TestPairedFixtureContrast
# ===========================================================================

class TestPairedFixtureContrast:
    """Lightweight assertions that paired fixtures share vendor but differ
    in the targeted variable."""

    def _load_by_id(self):
        records = load_expected(EXPECTED_PATH)
        return {r["invoice_id"]: r for r in records}

    def test_threshold_pair_same_amount(self):
        """INV-1057 and INV-1058 should have the same amount but differ in has_po."""
        by_id = self._load_by_id()
        a, b = by_id["INV-1057"], by_id["INV-1058"]
        assert a["expected_fields"]["amount"] == b["expected_fields"]["amount"]
        assert a["expected_fields"]["has_po"] != b["expected_fields"]["has_po"]

    def test_po_prose_pair_same_vendor(self):
        """INV-1059 and INV-1060 should share vendor and both be no_po."""
        by_id = self._load_by_id()
        a, b = by_id["INV-1059"], by_id["INV-1060"]
        assert a["expected_fields"]["vendor"] == b["expected_fields"]["vendor"]
        assert a["expected_fields"]["has_po"] is False
        assert b["expected_fields"]["has_po"] is False

    def test_vendor_alias_pair_different_suffix(self):
        """INV-1065 and INV-1066 should have different vendor names (alias variation)."""
        by_id = self._load_by_id()
        a, b = by_id["INV-1065"], by_id["INV-1066"]
        assert a["expected_fields"]["vendor"] != b["expected_fields"]["vendor"]
        # Both should contain the base vendor name
        assert "Acme Industrial Supply" in a["expected_fields"]["vendor"]
        assert "Acme Industrial Supply" in b["expected_fields"]["vendor"]

    def test_duplicate_totals_pair_same_vendor(self):
        """INV-1061 and INV-1062 should share vendor but differ in amount."""
        by_id = self._load_by_id()
        a, b = by_id["INV-1061"], by_id["INV-1062"]
        assert a["expected_fields"]["vendor"] == b["expected_fields"]["vendor"]
        assert a["expected_fields"]["amount"] != b["expected_fields"]["amount"]
