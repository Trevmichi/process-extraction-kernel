"""
tests/test_explanation.py
Comprehensive tests for the structured explanation module.
"""
from __future__ import annotations

import json
import pytest

from src.audit_parser import parse_audit_log
from src.explanation import (
    AmountExplanation,
    ArithmeticExplanation,
    ExceptionExplanation,
    ExplanationReport,
    ExtractionExplanation,
    MatchExplanation,
    OutcomeClassification,
    RetryAttemptSummary,
    RetryExplanation,
    RoutingDecisionSummary,
    RoutingExplanation,
    build_explanation,
)


# ===================================================================
# Helpers
# ===================================================================

def _j(obj: dict) -> str:
    """Shorthand: dict → JSON string (matching audit_log entry format)."""
    return json.dumps(obj)


def _parsed(*entries: str):
    """Build a ParsedAuditLog from JSON string entries."""
    return parse_audit_log(list(entries))


# ===================================================================
# Group 1: Empty / minimal input
# ===================================================================

class TestEmptyAndMinimal:

    def test_empty_log_returns_all_none_components(self):
        report = build_explanation(_parsed())
        assert report.extraction is None
        assert report.routing is None
        assert report.match is None
        assert report.exception is None
        assert report.retry is None
        assert report.amount is None

    def test_empty_log_outcome_unknown(self):
        report = build_explanation(_parsed())
        assert report.outcome.final_status == "UNKNOWN"
        assert report.outcome.category == "unknown"

    def test_explicit_final_status_preferred(self):
        report = build_explanation(_parsed(), final_status="APPROVED")
        assert report.outcome.final_status == "APPROVED"
        assert report.outcome.category == "success"

    def test_schema_version(self):
        report = build_explanation(_parsed())
        assert report.schema_version == "explanation_v1"

    def test_frozen(self):
        report = build_explanation(_parsed())
        with pytest.raises(AttributeError):
            report.schema_version = "v2"  # type: ignore[misc]


# ===================================================================
# Group 2: ExtractionExplanation
# ===================================================================

class TestExtractionExplanation:

    def test_llm_error_variant(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": False, "reasons": ["LLM_ERROR"],
        }))
        report = build_explanation(log)
        assert report.extraction is not None
        assert report.extraction.variant == "llm_error"
        assert report.extraction.valid is False
        assert report.extraction.failure_codes == ("LLM_ERROR",)

    def test_structural_variant(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": False,
            "failure_codes": ["STRUCT_MISSING_VENDOR", "STRUCT_NO_EVIDENCE_AMOUNT"],
            "status": "BAD_EXTRACTION",
        }))
        report = build_explanation(log)
        assert report.extraction is not None
        assert report.extraction.variant == "structural"
        assert report.extraction.failure_codes == (
            "STRUCT_MISSING_VENDOR", "STRUCT_NO_EVIDENCE_AMOUNT",
        )

    def test_verifier_valid(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": True, "reasons": [],
        }))
        report = build_explanation(log)
        assert report.extraction is not None
        assert report.extraction.variant == "verifier"
        assert report.extraction.valid is True
        assert report.extraction.failure_codes == ()

    def test_verifier_failure(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": False, "reasons": ["AMOUNT_MISMATCH", "PO_PATTERN_MISSING"],
        }))
        report = build_explanation(log)
        assert report.extraction is not None
        assert report.extraction.variant == "verifier"
        assert report.extraction.valid is False
        assert report.extraction.failure_codes == ("AMOUNT_MISMATCH", "PO_PATTERN_MISSING")

    def test_with_verifier_summary(self):
        log = _parsed(
            _j({
                "event": "extraction", "node": "ENTER_RECORD",
                "valid": True, "reasons": [],
            }),
            _j({
                "event": "verifier_summary", "valid": True,
                "failure_codes": [],
                "status_before": "NEW", "status_after": "DATA_EXTRACTED",
                "vendor": {"ok": True}, "amount": {"ok": True}, "has_po": {"ok": True},
            }),
        )
        report = build_explanation(log)
        ext = report.extraction
        assert ext is not None
        assert ext.status_before == "NEW"
        assert ext.status_after == "DATA_EXTRACTED"
        assert ext.field_results == {
            "vendor": {"ok": True},
            "amount": {"ok": True},
            "has_po": {"ok": True},
        }

    def test_without_verifier_summary(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": False, "reasons": ["LLM_ERROR"],
        }))
        report = build_explanation(log)
        ext = report.extraction
        assert ext is not None
        assert ext.status_before is None
        assert ext.status_after is None
        assert ext.field_results is None

    def test_extraction_count(self):
        log = _parsed(
            _j({"event": "extraction", "node": "ENTER_RECORD", "valid": False, "reasons": ["LLM_ERROR"]}),
            _j({"event": "extraction", "node": "ENTER_RECORD", "valid": True, "reasons": []}),
        )
        report = build_explanation(log)
        assert report.extraction is not None
        assert report.extraction.extraction_count == 2


# ===================================================================
# Group 3: RoutingExplanation
# ===================================================================

class TestRoutingExplanation:

    def test_single_route_decision(self):
        log = _parsed(_j({
            "event": "route_decision", "from_node": "n3",
            "candidates": [{"to": "n5", "condition": "status==\"APPROVED\"", "matched": True}],
            "selected": "n5", "reason": "condition_match",
        }))
        report = build_explanation(log)
        assert report.routing is not None
        assert report.routing.total_gateways == 1
        d = report.routing.decisions[0]
        assert d.gateway_id == "n3"
        assert d.selected == "n5"
        assert d.reason == "condition_match"
        assert d.candidate_count == 1
        assert d.matched_count == 1
        assert d.is_exception_route is False

    def test_multiple_decisions_ordered(self):
        log = _parsed(
            _j({"event": "route_decision", "from_node": "n1", "candidates": [], "selected": "n2", "reason": "single_edge"}),
            _j({"event": "route_decision", "from_node": "n3", "candidates": [], "selected": "n4", "reason": "unconditional_fallback"}),
            _j({"event": "route_decision", "from_node": "n5", "candidates": [], "selected": "n6", "reason": "condition_match"}),
        )
        report = build_explanation(log)
        assert report.routing is not None
        assert report.routing.total_gateways == 3
        ids = [d.gateway_id for d in report.routing.decisions]
        assert ids == ["n1", "n3", "n5"]

    def test_condition_match_counts(self):
        log = _parsed(_j({
            "event": "route_decision", "from_node": "n3",
            "candidates": [
                {"to": "n5", "condition": "status==\"APPROVED\"", "matched": True},
                {"to": "n6", "condition": "status==\"REJECTED\"", "matched": False},
                {"to": "n7", "condition": None, "matched": None},
            ],
            "selected": "n5", "reason": "condition_match",
        }))
        report = build_explanation(log)
        d = report.routing.decisions[0]
        assert d.candidate_count == 3
        assert d.matched_count == 1

    def test_ambiguous_route(self):
        log = _parsed(_j({
            "event": "route_decision", "from_node": "n3",
            "candidates": [
                {"to": "n5", "matched": True},
                {"to": "n6", "matched": True},
            ],
            "selected": None, "reason": "ambiguous_route",
        }))
        report = build_explanation(log)
        d = report.routing.decisions[0]
        assert d.is_exception_route is True
        assert d.matched_count == 2
        assert d.selected is None

    def test_no_route(self):
        log = _parsed(_j({
            "event": "route_decision", "from_node": "n3",
            "candidates": [
                {"to": "n5", "matched": False},
            ],
            "selected": None, "reason": "no_route",
        }))
        report = build_explanation(log)
        d = report.routing.decisions[0]
        assert d.is_exception_route is True


# ===================================================================
# Group 4: MatchExplanation
# ===================================================================

class TestMatchExplanation:

    def test_match_result_match(self):
        log = _parsed(
            _j({"event": "match_inputs", "node": "MATCH_3_WAY", "po_match": True, "match_3_way": None}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "MATCH", "source_flag": "po_match"}),
        )
        report = build_explanation(log)
        assert report.match is not None
        assert report.match.match_result == "MATCH"
        assert report.match.source_flag == "po_match"
        assert report.match.po_match_input is True
        assert report.match.match_3_way_input is None
        assert report.match.resolved_from == "po_match"

    def test_match_result_no_match(self):
        log = _parsed(
            _j({"event": "match_inputs", "node": "MATCH_3_WAY", "po_match": None, "match_3_way": False}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "NO_MATCH", "source_flag": "match_3_way"}),
        )
        report = build_explanation(log)
        assert report.match.match_result == "NO_MATCH"
        assert report.match.resolved_from == "match_3_way"

    def test_match_result_variance(self):
        log = _parsed(
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "VARIANCE", "source_flag": "match_3_way"}),
        )
        report = build_explanation(log)
        assert report.match.match_result == "VARIANCE"

    def test_match_result_unknown(self):
        log = _parsed(
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "UNKNOWN", "source_flag": None}),
        )
        report = build_explanation(log)
        assert report.match.match_result == "UNKNOWN"
        assert report.match.resolved_from == "none"

    def test_match_without_inputs(self):
        log = _parsed(
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "MATCH", "source_flag": "po_match"}),
        )
        report = build_explanation(log)
        assert report.match is not None
        assert report.match.po_match_input is None
        assert report.match.match_3_way_input is None
        assert report.match.resolved_from == "po_match"


# ===================================================================
# Group 5: ExceptionExplanation
# ===================================================================

class TestExceptionExplanation:

    def test_bad_extraction(self):
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc_bad_extraction",
            "reason": "BAD_EXTRACTION", "gateway": "n3",
        }))
        report = build_explanation(log)
        assert report.exception is not None
        assert report.exception.reason == "BAD_EXTRACTION"
        assert report.exception.expected_status == "EXCEPTION_BAD_EXTRACTION"
        assert report.exception.triggering_gateway == "n3"
        assert report.exception.node == "n_exc_bad_extraction"

    def test_no_route(self):
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc_no_route",
            "reason": "NO_ROUTE", "gateway": "n8",
        }))
        report = build_explanation(log)
        assert report.exception.expected_status == "EXCEPTION_NO_ROUTE"

    def test_unknown_reason_falls_back(self):
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc",
            "reason": "NEVER_SEEN_BEFORE", "gateway": "n99",
        }))
        report = build_explanation(log)
        assert report.exception.expected_status == "EXCEPTION_UNKNOWN"

    def test_gateway_preserved(self):
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc_ambiguous",
            "reason": "AMBIGUOUS_ROUTE", "gateway": "n16",
        }))
        report = build_explanation(log)
        assert report.exception.triggering_gateway == "n16"


# ===================================================================
# Group 6: RetryExplanation
# ===================================================================

class TestRetryExplanation:

    def test_single_retry_success(self):
        log = _parsed(_j({
            "event": "critic_retry_executed", "node": "CRITIC_RETRY",
            "attempt": 1, "valid": True, "failure_codes": [], "status": "DATA_EXTRACTED",
        }))
        report = build_explanation(log)
        assert report.retry is not None
        assert report.retry.total_attempts == 1
        assert report.retry.final_valid is True
        assert report.retry.final_status == "DATA_EXTRACTED"
        assert report.retry.attempts[0].attempt == 1

    def test_multiple_retries_then_fail(self):
        log = _parsed(
            _j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                "attempt": 1, "valid": False, "failure_codes": ["AMOUNT_MISMATCH"], "status": "BAD_EXTRACTION"}),
            _j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                "attempt": 2, "valid": False, "failure_codes": ["AMOUNT_MISMATCH"], "status": "BAD_EXTRACTION"}),
        )
        report = build_explanation(log)
        assert report.retry.total_attempts == 2
        assert report.retry.final_valid is False
        assert report.retry.final_status == "BAD_EXTRACTION"

    def test_retry_attempt_ordering(self):
        log = _parsed(
            _j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                "attempt": 1, "valid": False, "failure_codes": ["X"], "status": "BAD_EXTRACTION"}),
            _j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                "attempt": 2, "valid": True, "failure_codes": [], "status": "DATA_EXTRACTED"}),
        )
        report = build_explanation(log)
        attempts = [a.attempt for a in report.retry.attempts]
        assert attempts == [1, 2]

    def test_no_retries(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": True, "reasons": [],
        }))
        report = build_explanation(log)
        assert report.retry is None


# ===================================================================
# Group 7: AmountExplanation
# ===================================================================

class TestAmountExplanation:

    def test_single_candidate(self):
        log = _parsed(_j({
            "event": "amount_candidates",
            "candidates": [{"raw": "$500.00", "parsed": 500.0, "keyword": "total"}],
            "selected": 500.0, "winning_keyword": "total",
        }))
        report = build_explanation(log)
        assert report.amount is not None
        assert report.amount.candidate_count == 1
        assert report.amount.selected == 500.0
        assert report.amount.winning_keyword == "total"
        assert report.amount.ambiguous is False

    def test_multiple_candidates_ambiguous(self):
        log = _parsed(_j({
            "event": "amount_candidates",
            "candidates": [
                {"raw": "$500", "parsed": 500.0},
                {"raw": "$750", "parsed": 750.0},
            ],
            "selected": 750.0, "winning_keyword": "amount due",
        }))
        report = build_explanation(log)
        assert report.amount.ambiguous is True
        assert report.amount.candidate_count == 2

    def test_no_amount_event(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": True, "reasons": [],
        }))
        report = build_explanation(log)
        assert report.amount is None


# ===================================================================
# Group 8: OutcomeClassification
# ===================================================================

class TestOutcomeClassification:

    def test_success(self):
        report = build_explanation(_parsed(), final_status="APPROVED")
        assert report.outcome.category == "success"
        assert report.outcome.is_terminal is True
        assert report.outcome.is_exception is False

    def test_exception(self):
        report = build_explanation(_parsed(), final_status="EXCEPTION_NO_ROUTE")
        assert report.outcome.category == "exception"
        assert report.outcome.is_terminal is True
        assert report.outcome.is_exception is True

    def test_rejection(self):
        report = build_explanation(_parsed(), final_status="REJECTED")
        assert report.outcome.category == "rejection"
        assert report.outcome.is_terminal is True

    def test_in_progress(self):
        report = build_explanation(_parsed(), final_status="NEW")
        assert report.outcome.category == "in_progress"
        assert report.outcome.is_terminal is False

    def test_inferred_from_exception_event(self):
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc",
            "reason": "NO_ROUTE", "gateway": "n8",
        }))
        report = build_explanation(log)
        assert report.outcome.final_status == "EXCEPTION_NO_ROUTE"
        assert report.outcome.category == "exception"

    def test_inferred_from_verifier_summary(self):
        log = _parsed(_j({
            "event": "verifier_summary", "valid": True,
            "failure_codes": [],
            "status_before": "NEW", "status_after": "DATA_EXTRACTED",
            "vendor": {}, "amount": {}, "has_po": {},
        }))
        report = build_explanation(log)
        assert report.outcome.final_status == "DATA_EXTRACTED"

    def test_inferred_from_extraction(self):
        log = _parsed(_j({
            "event": "extraction", "node": "ENTER_RECORD",
            "valid": False,
            "failure_codes": ["STRUCT_MISSING_VENDOR"],
            "status": "BAD_EXTRACTION",
        }))
        report = build_explanation(log)
        assert report.outcome.final_status == "BAD_EXTRACTION"

    def test_explicit_overrides_inferred(self):
        """Explicit final_status is preferred even when events suggest otherwise."""
        log = _parsed(_j({
            "event": "exception_station", "node": "n_exc",
            "reason": "NO_ROUTE", "gateway": "n8",
        }))
        report = build_explanation(log, final_status="APPROVED")
        assert report.outcome.final_status == "APPROVED"
        assert report.outcome.category == "success"


# ===================================================================
# Group 9: to_dict serialization
# ===================================================================

class TestToDict:

    def test_full_report(self):
        log = _parsed(
            _j({"event": "extraction", "node": "ENTER_RECORD", "valid": True, "reasons": []}),
            _j({"event": "verifier_summary", "valid": True, "failure_codes": [],
                "status_before": "NEW", "status_after": "DATA_EXTRACTED",
                "vendor": {"ok": True}, "amount": {"ok": True}, "has_po": {"ok": True}}),
            _j({"event": "route_decision", "from_node": "n3", "candidates": [], "selected": "n5", "reason": "single_edge"}),
            _j({"event": "match_inputs", "node": "MATCH_3_WAY", "po_match": True, "match_3_way": None}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "MATCH", "source_flag": "po_match"}),
            _j({"event": "amount_candidates", "candidates": [{"raw": "$100", "parsed": 100.0}], "selected": 100.0, "winning_keyword": "total"}),
        )
        report = build_explanation(log, final_status="APPROVED")
        d = report.to_dict()

        assert d["schema_version"] == "explanation_v1"
        assert d["extraction"] is not None
        assert d["routing"] is not None
        assert d["match"] is not None
        assert d["amount"] is not None
        assert d["outcome"]["final_status"] == "APPROVED"

        # Verify JSON-serializable
        json.dumps(d)

    def test_sparse_report(self):
        report = build_explanation(_parsed(), final_status="NEW")
        d = report.to_dict()

        assert d["extraction"] is None
        assert d["routing"] is None
        assert d["match"] is None
        assert d["exception"] is None
        assert d["retry"] is None
        assert d["amount"] is None
        assert d["outcome"]["category"] == "in_progress"

        # Verify JSON-serializable
        json.dumps(d)


# ===================================================================
# Group 10: Integration
# ===================================================================

class TestIntegration:

    def test_happy_path(self):
        """Full successful invoice processing trail."""
        log = _parsed(
            _j({"event": "extraction", "node": "ENTER_RECORD", "valid": True, "reasons": []}),
            _j({"event": "verifier_summary", "valid": True, "failure_codes": [],
                "status_before": "NEW", "status_after": "DATA_EXTRACTED",
                "vendor": {"ok": True, "value": "Acme Corp"},
                "amount": {"ok": True, "value": 250.0, "delta": 0.0},
                "has_po": {"ok": True, "value": True}}),
            _j({"event": "amount_candidates",
                "candidates": [{"raw": "$250.00", "parsed": 250.0, "keyword": "total"}],
                "selected": 250.0, "winning_keyword": "total"}),
            _j({"event": "route_decision", "from_node": "n3",
                "candidates": [{"to": "n4", "condition": 'status=="DATA_EXTRACTED"', "matched": True}],
                "selected": "n4", "reason": "condition_match"}),
            _j({"event": "match_inputs", "node": "MATCH_3_WAY", "po_match": True, "match_3_way": None}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY", "match_result": "MATCH", "source_flag": "po_match"}),
            _j({"event": "route_decision", "from_node": "n8",
                "candidates": [{"to": "n10", "condition": 'has_po==true', "matched": True}],
                "selected": "n10", "reason": "condition_match"}),
            "Executed APPROVE [role_ap_clerk] at n32",
        )
        report = build_explanation(log, final_status="APPROVED")

        assert report.extraction.valid is True
        assert report.extraction.variant == "verifier"
        assert report.extraction.extraction_count == 1
        assert report.routing.total_gateways == 2
        assert report.match.match_result == "MATCH"
        assert report.match.resolved_from == "po_match"
        assert report.exception is None
        assert report.retry is None
        assert report.amount.selected == 250.0
        assert report.outcome.category == "success"

    def test_exception_path(self):
        """Extraction failure leading to exception station."""
        log = _parsed(
            _j({"event": "extraction", "node": "ENTER_RECORD", "valid": False, "reasons": ["LLM_ERROR"]}),
            _j({"event": "route_decision", "from_node": "n3",
                "candidates": [{"to": "n_exc", "condition": 'status=="BAD_EXTRACTION"', "matched": True}],
                "selected": "n_exc", "reason": "condition_match"}),
            _j({"event": "exception_station", "node": "n_exc_bad_extraction",
                "reason": "BAD_EXTRACTION", "gateway": "n3"}),
        )
        report = build_explanation(log)

        assert report.extraction.variant == "llm_error"
        assert report.extraction.valid is False
        assert report.routing.total_gateways == 1
        assert report.exception.reason == "BAD_EXTRACTION"
        assert report.exception.expected_status == "EXCEPTION_BAD_EXTRACTION"
        assert report.outcome.final_status == "EXCEPTION_BAD_EXTRACTION"
        assert report.outcome.category == "exception"
        assert report.retry is None


# ===================================================================
# Group 11: ArithmeticExplanation
# ===================================================================

class TestArithmeticExplanation:

    def test_build_from_passing_event(self):
        log = _parsed(_j({
            "event": "arithmetic_check",
            "checks_run": ["total_sum", "tax_rate"],
            "passed": True,
            "codes": [],
            "total_sum": {"subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                          "expected": 447.0, "actual": 447.0, "delta": 0.0},
            "tax_rate": {"rate_pct": 8.0, "computed": 32.0, "stated": 32.0, "delta": 0.0},
        }))
        report = build_explanation(log, final_status="DATA_EXTRACTED")
        assert report.arithmetic is not None
        assert report.arithmetic.passed is True
        assert report.arithmetic.failure_codes == ()
        assert report.arithmetic.check_count == 2
        assert report.arithmetic.total_sum_delta == 0.0
        assert report.arithmetic.tax_rate_delta == 0.0

    def test_build_from_failing_event(self):
        log = _parsed(_j({
            "event": "arithmetic_check",
            "checks_run": ["total_sum"],
            "passed": False,
            "codes": ["ARITH_TOTAL_MISMATCH"],
            "total_sum": {"subtotal": 200.0, "taxes": 0.0, "fees": 0.0,
                          "expected": 200.0, "actual": 500.0, "delta": 300.0},
        }))
        report = build_explanation(log, final_status="BAD_EXTRACTION")
        assert report.arithmetic is not None
        assert report.arithmetic.passed is False
        assert report.arithmetic.failure_codes == ("ARITH_TOTAL_MISMATCH",)
        assert report.arithmetic.total_sum_delta == 300.0
        assert report.arithmetic.tax_rate_delta is None
        assert report.arithmetic.check_count == 1

    def test_no_event_returns_none(self):
        report = build_explanation(_parsed(), final_status="NEW")
        assert report.arithmetic is None

    def test_to_dict_serialization(self):
        log = _parsed(_j({
            "event": "arithmetic_check",
            "checks_run": ["total_sum"],
            "passed": True,
            "codes": [],
            "total_sum": {"delta": 0.0},
        }))
        report = build_explanation(log, final_status="DATA_EXTRACTED")
        d = report.to_dict()
        assert d["arithmetic"] is not None
        assert d["arithmetic"]["passed"] is True
        assert d["arithmetic"]["checks_run"] == ["total_sum"]
        assert d["arithmetic"]["check_count"] == 1
        # JSON-serializable
        json.dumps(d)

    def test_sparse_report_arithmetic_none(self):
        report = build_explanation(_parsed(), final_status="NEW")
        d = report.to_dict()
        assert d["arithmetic"] is None
