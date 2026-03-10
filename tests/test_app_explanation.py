"""
tests/test_app_explanation.py
Parity tests proving ExplanationReport fields match ui_audit extractor
results for representative audit_logs.  These verify that the app.py
data-source swap (Phase 7) produces identical behavior.
"""
from __future__ import annotations

import json

from src.audit_parser import (
    ArithmeticCheckEvent,
    ExceptionStationEvent,
    ExtractionEvent,
    PlainTextEntry,
    RouteDecisionEvent,
    RouteStepEntry,
    parse_audit_log,
)
from src.explanation import build_explanation
from src.ui_audit import (
    extract_exception_event,
    extract_match_event,
    extract_verifier_event,
)


# ===================================================================
# Helpers
# ===================================================================

def _j(obj: dict) -> str:
    return json.dumps(obj)


# ===================================================================
# Parity: exception
# ===================================================================

class TestExceptionParity:

    def test_exception_reason_matches(self):
        log = [_j({"event": "exception_station", "node": "n_exc_bad",
                    "reason": "BAD_EXTRACTION", "gateway": "n3"})]
        legacy = extract_exception_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert report.exception is not None
        assert report.exception.reason == legacy["reason"]
        assert report.exception.node == legacy["node"]

    def test_exception_none_when_absent(self):
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": True, "reasons": []})]
        legacy = extract_exception_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert legacy is None
        assert report.exception is None

    def test_exception_last_wins(self):
        """Multiple exception events — both paths take the last one."""
        log = [
            _j({"event": "exception_station", "node": "n1",
                "reason": "NO_ROUTE", "gateway": "n5"}),
            _j({"event": "exception_station", "node": "n2",
                "reason": "AMBIGUOUS_ROUTE", "gateway": "n8"}),
        ]
        legacy = extract_exception_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert legacy["reason"] == "AMBIGUOUS_ROUTE"
        assert report.exception.reason == "AMBIGUOUS_ROUTE"


# ===================================================================
# Parity: verifier / extraction
# ===================================================================

class TestVerifierParity:

    def test_extraction_valid_matches(self):
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": True, "reasons": []})]
        legacy = extract_verifier_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert report.extraction is not None
        assert report.extraction.valid == legacy["valid"]

    def test_extraction_failure_codes_match(self):
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": False,
                    "reasons": ["AMOUNT_MISMATCH", "PO_PATTERN_MISSING"]})]
        legacy = extract_verifier_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert report.extraction.valid is False
        assert list(report.extraction.failure_codes) == legacy["reasons"]

    def test_extraction_none_when_absent(self):
        log = [_j({"event": "route_decision", "from_node": "n3",
                    "candidates": [], "selected": "n5", "reason": "single_edge"})]
        legacy = extract_verifier_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert legacy is None
        assert report.extraction is None


# ===================================================================
# Parity: match
# ===================================================================

class TestMatchParity:

    def test_match_result_matches(self):
        log = [_j({"event": "match_result_set", "node": "MATCH_3_WAY",
                    "match_result": "MATCH", "source_flag": "po_match"})]
        legacy = extract_match_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert report.match is not None
        assert report.match.match_result == legacy["match_result"]
        assert report.match.source_flag == legacy["source_flag"]

    def test_match_none_when_absent(self):
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": True, "reasons": []})]
        legacy = extract_match_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert legacy is None
        assert report.match is None

    def test_match_no_source_flag(self):
        log = [_j({"event": "match_result_set", "node": "MATCH_3_WAY",
                    "match_result": "UNKNOWN", "source_flag": None})]
        legacy = extract_match_event(log)
        parsed = parse_audit_log(log)
        report = build_explanation(parsed)
        assert report.match.match_result == legacy["match_result"]
        assert report.match.source_flag is None


# ===================================================================
# Outcome classification
# ===================================================================

class TestOutcomeClassification:

    def test_approved_is_success(self):
        report = build_explanation(parse_audit_log([]), final_status="APPROVED")
        assert report.outcome.category == "success"

    def test_paid_is_success(self):
        report = build_explanation(parse_audit_log([]), final_status="PAID")
        assert report.outcome.category == "success"

    def test_exception_no_route(self):
        report = build_explanation(parse_audit_log([]), final_status="EXCEPTION_NO_ROUTE")
        assert report.outcome.category == "exception"
        assert report.outcome.is_exception is True

    def test_exception_no_po(self):
        report = build_explanation(parse_audit_log([]), final_status="EXCEPTION_NO_PO")
        assert report.outcome.category == "exception"

    def test_rejected_is_rejection(self):
        report = build_explanation(parse_audit_log([]), final_status="REJECTED")
        assert report.outcome.category == "rejection"

    def test_escalated_is_rejection(self):
        report = build_explanation(parse_audit_log([]), final_status="ESCALATED")
        assert report.outcome.category == "rejection"

    def test_bad_extraction_is_rejection(self):
        report = build_explanation(parse_audit_log([]), final_status="BAD_EXTRACTION")
        assert report.outcome.category == "rejection"

    def test_new_is_in_progress(self):
        report = build_explanation(parse_audit_log([]), final_status="NEW")
        assert report.outcome.category == "in_progress"

    def test_unknown_status(self):
        report = build_explanation(parse_audit_log([]), final_status="NEVER_SEEN")
        assert report.outcome.category == "unknown"


# ===================================================================
# Explicit status takes precedence over event-derived signals
# ===================================================================

class TestStatusPrecedence:

    def test_explicit_overrides_exception_inference(self):
        """When status_val from state says APPROVED but audit_log has
        an exception event, the explicit status wins."""
        log = [_j({"event": "exception_station", "node": "n_exc",
                    "reason": "NO_ROUTE", "gateway": "n8"})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="APPROVED")
        # Explicit status wins for outcome classification
        assert report.outcome.final_status == "APPROVED"
        assert report.outcome.category == "success"
        # But exception component is still populated from audit events
        assert report.exception is not None
        assert report.exception.reason == "NO_ROUTE"

    def test_explicit_overrides_extraction_inference(self):
        """When status_val from state says DATA_EXTRACTED but audit_log
        has a BAD_EXTRACTION extraction event, explicit wins."""
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": False,
                    "failure_codes": ["STRUCT_MISSING_VENDOR"],
                    "status": "BAD_EXTRACTION"})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="DATA_EXTRACTED")
        assert report.outcome.final_status == "DATA_EXTRACTED"
        assert report.outcome.category == "in_progress"
        # Extraction component still reflects the audit event
        assert report.extraction.valid is False


# ===================================================================
# Empty log
# ===================================================================

class TestEmptyLog:

    def test_empty_log_all_none(self):
        parsed = parse_audit_log([])
        report = build_explanation(parsed, final_status="NEW")
        assert report.exception is None
        assert report.extraction is None
        assert report.match is None
        assert report.routing is None
        assert report.outcome.final_status == "NEW"
        assert report.outcome.category == "in_progress"


# ===================================================================
# Realistic multi-event parity
# ===================================================================

class TestRealisticParity:

    def test_full_happy_path_parity(self):
        """All 4 extractor results match ExplanationReport for a
        realistic successful invoice processing audit log."""
        log = [
            _j({"event": "extraction", "node": "ENTER_RECORD",
                "valid": True, "reasons": []}),
            _j({"event": "verifier_summary", "valid": True,
                "failure_codes": [],
                "status_before": "NEW", "status_after": "DATA_EXTRACTED",
                "vendor": {"ok": True}, "amount": {"ok": True},
                "has_po": {"ok": True}}),
            _j({"event": "route_decision", "from_node": "n3",
                "candidates": [{"to": "n4", "matched": True}],
                "selected": "n4", "reason": "condition_match"}),
            _j({"event": "match_inputs", "node": "MATCH_3_WAY",
                "po_match": True, "match_3_way": None}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY",
                "match_result": "MATCH", "source_flag": "po_match"}),
            "Executed APPROVE [role_ap_clerk] at n32",
        ]

        # Legacy extractors
        exc_legacy = extract_exception_event(log)
        ver_legacy = extract_verifier_event(log)
        match_legacy = extract_match_event(log)

        # ExplanationReport
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="APPROVED")

        # Exception: both None
        assert exc_legacy is None
        assert report.exception is None

        # Verifier: valid matches
        assert ver_legacy is not None
        assert report.extraction is not None
        assert report.extraction.valid == ver_legacy["valid"]

        # Match: result + source match
        assert match_legacy is not None
        assert report.match is not None
        assert report.match.match_result == match_legacy["match_result"]
        assert report.match.source_flag == match_legacy["source_flag"]

        # Outcome
        assert report.outcome.category == "success"


# ===================================================================
# Arithmetic display
# ===================================================================

class TestArithmeticDisplay:

    def test_arithmetic_pass_available_for_caption(self):
        """When arithmetic checks pass, report has data for a pass caption."""
        log = [_j({"event": "arithmetic_check",
                    "checks_run": ["total_sum"], "passed": True,
                    "codes": [], "total_sum": {"delta": 0.0}})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="DATA_EXTRACTED")
        assert report.arithmetic is not None
        assert report.arithmetic.passed is True

    def test_arithmetic_failure_with_codes_and_deltas(self):
        """When arithmetic checks fail, report surfaces codes + deltas for warning."""
        log = [_j({"event": "arithmetic_check",
                    "checks_run": ["total_sum", "tax_rate"],
                    "passed": False,
                    "codes": ["ARITH_TOTAL_MISMATCH", "ARITH_TAX_RATE_MISMATCH"],
                    "total_sum": {"delta": 300.0},
                    "tax_rate": {"delta": 100.0}})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="BAD_EXTRACTION")
        assert report.arithmetic is not None
        assert report.arithmetic.passed is False
        assert "ARITH_TOTAL_MISMATCH" in report.arithmetic.failure_codes
        assert report.arithmetic.total_sum_delta == 300.0
        assert report.arithmetic.tax_rate_delta == 100.0

    def test_no_arithmetic_event_is_none(self):
        """No arithmetic_check event → arithmetic is None, no display."""
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": True, "reasons": []})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="DATA_EXTRACTED")
        assert report.arithmetic is None


# ===================================================================
# Routing display
# ===================================================================

class TestRoutingDisplay:

    def test_gateway_decisions_produce_table_data(self):
        """ExplanationReport.routing surfaces gateway decisions for the table."""
        log = [
            _j({"event": "route_decision", "from_node": "n3",
                "candidates": [
                    {"to": "n4", "condition": "has_po == true", "matched": True},
                    {"to": "n5", "condition": "has_po == false", "matched": False},
                ],
                "selected": "n4", "reason": "condition_match"}),
        ]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="DATA_EXTRACTED")
        assert report.routing is not None
        assert report.routing.total_gateways == 1
        d = report.routing.decisions[0]
        assert d.gateway_id == "n3"
        assert d.selected == "n4"
        assert d.reason == "condition_match"
        assert d.candidate_count == 2

    def test_route_steps_parsed_from_audit_log(self):
        """RouteStepEntry instances are available from parsed.entries."""
        log = ["Executed APPROVE [role_ap_clerk] at n32"]
        parsed = parse_audit_log(log)
        steps = [e for e in parsed.entries if isinstance(e, RouteStepEntry)]
        assert len(steps) == 1
        assert steps[0].intent == "APPROVE"
        assert steps[0].node_id == "n32"
        assert steps[0].actor == "role_ap_clerk"

    def test_no_routing_returns_none(self):
        """No route_decision events → explanation.routing is None."""
        log = [_j({"event": "extraction", "node": "ENTER_RECORD",
                    "valid": True, "reasons": []})]
        parsed = parse_audit_log(log)
        report = build_explanation(parsed, final_status="DATA_EXTRACTED")
        assert report.routing is None


# ===================================================================
# Audit trail entry formatting
# ===================================================================

def _get_format_fn():
    """Extract _format_audit_entry from app.py without executing module body.

    app.py has Streamlit side-effects at module level, so we compile only
    the function definition in an isolated namespace.
    """
    import ast
    import textwrap
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "app.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    # Find the function definition node
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_format_audit_entry":
            func_src = ast.get_source_segment(src.read_text(encoding="utf-8"), node)
            break
    else:
        raise RuntimeError("_format_audit_entry not found in app.py")

    # Build a minimal namespace with the types the function needs
    from src.audit_parser import (
        AmountCandidatesEvent,
        ArithmeticCheckEvent,
        CriticRetryEvent,
        ExceptionStationEvent,
        ExtractionEvent,
        MatchInputsEvent,
        MatchResultSetEvent,
        PlainTextEntry,
        RouteDecisionEvent,
        RouteRecordEvent,
        RouteStepEntry,
        SequentialDispatchEvent,
        UnknownJsonEntry,
        VerifierSummaryEvent,
    )
    ns: dict = {
        "AmountCandidatesEvent": AmountCandidatesEvent,
        "ArithmeticCheckEvent": ArithmeticCheckEvent,
        "CriticRetryEvent": CriticRetryEvent,
        "ExceptionStationEvent": ExceptionStationEvent,
        "ExtractionEvent": ExtractionEvent,
        "MatchInputsEvent": MatchInputsEvent,
        "MatchResultSetEvent": MatchResultSetEvent,
        "PlainTextEntry": PlainTextEntry,
        "RouteDecisionEvent": RouteDecisionEvent,
        "RouteRecordEvent": RouteRecordEvent,
        "RouteStepEntry": RouteStepEntry,
        "SequentialDispatchEvent": SequentialDispatchEvent,
        "UnknownJsonEntry": UnknownJsonEntry,
        "VerifierSummaryEvent": VerifierSummaryEvent,
    }
    exec(compile(func_src, str(src), "exec"), ns)
    return ns["_format_audit_entry"]


class TestFormatAuditEntry:

    _fmt = staticmethod(_get_format_fn())

    def test_extraction_valid(self):
        entry = ExtractionEvent(
            event="extraction", node="ENTER_RECORD", valid=True,
            reasons=(), failure_codes=None, status=None,
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "✅"
        assert tag == "EXTRACT"
        assert "valid" in summary
        assert "verifier" in summary

    def test_extraction_failed_with_codes(self):
        entry = ExtractionEvent(
            event="extraction", node="ENTER_RECORD", valid=False,
            reasons=("AMOUNT_MISMATCH",), failure_codes=None, status=None,
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "❌"
        assert tag == "EXTRACT"
        assert "failed" in summary
        assert "AMOUNT_MISMATCH" in summary

    def test_exception_station(self):
        entry = ExceptionStationEvent(
            event="exception_station", node="n_exc_bad",
            reason="BAD_EXTRACTION", gateway="n3",
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "⚠️"
        assert tag == "EXCEPTION"
        assert "BAD_EXTRACTION" in summary
        assert "n3" in summary

    def test_arithmetic_passed(self):
        entry = ArithmeticCheckEvent(
            event="arithmetic_check", checks_run=("total_sum",),
            passed=True, codes=(), total_sum=None, tax_rate=None,
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "✅"
        assert tag == "ARITHMETIC"
        assert "passed" in summary

    def test_arithmetic_failed_with_codes(self):
        entry = ArithmeticCheckEvent(
            event="arithmetic_check", checks_run=("total_sum",),
            passed=False, codes=("ARITH_TOTAL_MISMATCH",),
            total_sum={"delta": 300.0}, tax_rate=None,
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "❌"
        assert tag == "ARITHMETIC"
        assert "failed" in summary
        assert "ARITH_TOTAL_MISMATCH" in summary

    def test_route_decision(self):
        entry = RouteDecisionEvent(
            event="route_decision", from_node="n3",
            candidates=({"to": "n4", "matched": True},),
            selected="n4", reason="condition_match",
        )
        icon, tag, summary = self._fmt(entry)
        assert icon == "▶"
        assert tag == "ROUTE"
        assert "n3" in summary
        assert "n4" in summary
        assert "1 candidates" in summary

    def test_plain_text(self):
        entry = PlainTextEntry(raw="Some unstructured log line")
        icon, tag, summary = self._fmt(entry)
        assert icon == "📝"
        assert tag == "TEXT"
        assert summary == "Some unstructured log line"


# ===================================================================
# Session history outcome category
# ===================================================================

def _get_outcome_fn():
    """Extract _get_outcome_category from app.py via AST."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "app.py"
    source_text = src.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_get_outcome_category":
            func_src = ast.get_source_segment(source_text, node)
            break
    else:
        raise RuntimeError("_get_outcome_category not found in app.py")
    ns: dict = {}
    exec(compile(func_src, str(src), "exec"), ns)
    return ns["_get_outcome_category"]


class TestOutcomeCategoryHelper:

    _fn = staticmethod(_get_outcome_fn())

    def test_success_from_explanation(self):
        item = {"status": "APPROVED", "explanation": {
            "outcome": {"category": "success", "final_status": "APPROVED"}}}
        assert self._fn(item) == "success"

    def test_exception_from_explanation(self):
        item = {"status": "EXCEPTION_NO_PO", "explanation": {
            "outcome": {"category": "exception", "final_status": "EXCEPTION_NO_PO"}}}
        assert self._fn(item) == "exception"

    def test_rejection_from_explanation(self):
        item = {"status": "REJECTED", "explanation": {
            "outcome": {"category": "rejection", "final_status": "REJECTED"}}}
        assert self._fn(item) == "rejection"

    def test_fallback_approved_without_explanation(self):
        """Old history item without explanation key — derives from status."""
        item = {"status": "APPROVED"}
        assert self._fn(item) == "success"

    def test_fallback_exception_without_explanation(self):
        item = {"status": "EXCEPTION_NO_ROUTE"}
        assert self._fn(item) == "exception"

    def test_fallback_rejection_without_explanation(self):
        item = {"status": "BAD_EXTRACTION"}
        assert self._fn(item) == "rejection"

    def test_partial_explanation_missing_outcome(self):
        """Explanation dict exists but missing outcome key."""
        item = {"status": "PAID", "explanation": {"schema_version": "v1"}}
        assert self._fn(item) == "success"  # falls back to status

    def test_partial_explanation_missing_category(self):
        """Outcome dict exists but missing category key."""
        item = {"status": "NEW", "explanation": {"outcome": {"final_status": "NEW"}}}
        assert self._fn(item) == "in_progress"  # falls back to status

    def test_outcome_column_uses_structured_category(self):
        """Verify dataframe-building expectation: Outcome derived from explanation."""
        items = [
            {"invoice_id": "INV-1", "vendor": "Acme", "amount": 100,
             "status": "APPROVED", "explanation": {
                 "outcome": {"category": "success", "final_status": "APPROVED"}}},
            {"invoice_id": "INV-2", "vendor": "Beta", "amount": 200,
             "status": "REJECTED"},
        ]
        outcomes = [self._fn(r) for r in items]
        assert outcomes == ["success", "rejection"]


# ===================================================================
# Session history summary
# ===================================================================

def _get_summary_fn():
    """Extract _get_history_summary (and its dependency _get_outcome_category)
    from app.py via AST."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "app.py"
    source_text = src.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    funcs: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_get_outcome_category", "_get_history_summary",
        ):
            funcs[node.name] = ast.get_source_segment(source_text, node)
    if "_get_history_summary" not in funcs:
        raise RuntimeError("_get_history_summary not found in app.py")
    ns: dict = {}
    # _get_history_summary calls _get_outcome_category, so compile both
    for name in ("_get_outcome_category", "_get_history_summary"):
        if name in funcs:
            exec(compile(funcs[name], str(src), "exec"), ns)
    return ns["_get_history_summary"]


class TestHistorySummary:

    _fn = staticmethod(_get_summary_fn())

    def test_exception_summary(self):
        item = {"status": "EXCEPTION_NO_PO", "explanation": {
            "exception": {"reason": "NO_PO", "node": "n_exc"},
            "outcome": {"category": "exception"}}}
        assert self._fn(item) == "Exception: NO_PO"

    def test_extraction_failure_with_codes(self):
        item = {"status": "BAD_EXTRACTION", "explanation": {
            "extraction": {"valid": False,
                           "failure_codes": ["AMBIGUOUS_AMOUNT_EVIDENCE",
                                             "PO_PATTERN_MISSING"]},
            "outcome": {"category": "rejection"}}}
        assert self._fn(item) == "Extraction failed: AMBIGUOUS_AMOUNT_EVIDENCE, PO_PATTERN_MISSING"

    def test_arithmetic_failure_with_total_delta(self):
        item = {"status": "BAD_EXTRACTION", "explanation": {
            "arithmetic": {"passed": False,
                           "failure_codes": ["ARITH_TOTAL_MISMATCH"],
                           "total_sum_delta": 300.0},
            "outcome": {"category": "rejection"}}}
        assert self._fn(item) == "Arithmetic failed: ARITH_TOTAL_MISMATCH (Δ 300.0)"

    def test_arithmetic_failure_with_tax_delta_only(self):
        item = {"status": "BAD_EXTRACTION", "explanation": {
            "arithmetic": {"passed": False,
                           "failure_codes": ["ARITH_TAX_RATE_MISMATCH"],
                           "tax_rate_delta": 0.05},
            "outcome": {"category": "rejection"}}}
        assert self._fn(item) == "Arithmetic failed: ARITH_TAX_RATE_MISMATCH (Δ 0.05)"

    def test_match_with_source(self):
        item = {"status": "APPROVED", "explanation": {
            "match": {"match_result": "MATCH", "source_flag": "po_match"},
            "outcome": {"category": "success"}}}
        assert self._fn(item) == "Match: MATCH via po_match"

    def test_match_without_source(self):
        item = {"status": "APPROVED", "explanation": {
            "match": {"match_result": "UNKNOWN"},
            "outcome": {"category": "success"}}}
        assert self._fn(item) == "Match: UNKNOWN"

    def test_clean_pass(self):
        """Explanation present, success category, no issues -> Clean pass."""
        item = {"status": "APPROVED", "explanation": {
            "outcome": {"category": "success"}}}
        assert self._fn(item) == "Clean pass"

    def test_old_item_without_explanation(self):
        """Legacy item without explanation -> status fallback, never Clean pass."""
        item = {"status": "APPROVED"}
        assert self._fn(item) == "Status: APPROVED"

    def test_partial_malformed_explanation(self):
        """Malformed explanation dict -> does not crash, falls back."""
        item = {"status": "PAID", "explanation": {"garbage": 42}}
        # No matching signal, but explanation exists and outcome fallback
        # _get_outcome_category falls back to status -> "success" -> "Clean pass"
        result = self._fn(item)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_priority_exception_over_match(self):
        """Item with both exception and match -> exception wins (first-match)."""
        item = {"status": "EXCEPTION_NO_PO", "explanation": {
            "exception": {"reason": "NO_PO", "node": "n_exc"},
            "match": {"match_result": "NO_MATCH", "source_flag": "po_match"},
            "outcome": {"category": "exception"}}}
        assert self._fn(item) == "Exception: NO_PO"


# ===================================================================
# Operator review panel
# ===================================================================

def _get_operator_review_fn():
    """Extract _build_operator_review from app.py via AST."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "app.py"
    source_text = src.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_operator_review":
            func_src = ast.get_source_segment(source_text, node)
            break
    else:
        raise RuntimeError("_build_operator_review not found in app.py")
    ns: dict = {}
    exec(compile(func_src, str(src), "exec"), ns)
    return ns["_build_operator_review"]


def _make_report(*, outcome_category="exception", final_status="EXCEPTION_NO_PO",
                 exception=None, extraction=None, arithmetic=None,
                 match=None, retry=None):
    """Build a minimal ExplanationReport for operator review tests."""
    from src.explanation import (
        ExplanationReport,
        OutcomeClassification,
    )
    return ExplanationReport(
        schema_version="v1",
        extraction=extraction,
        routing=None,
        match=match,
        exception=exception,
        retry=retry,
        amount=None,
        arithmetic=arithmetic,
        outcome=OutcomeClassification(
            final_status=final_status,
            is_terminal=True,
            is_exception=outcome_category == "exception",
            category=outcome_category,
        ),
    )


class TestOperatorReview:

    _fn = staticmethod(_get_operator_review_fn())

    def test_success_returns_none(self):
        report = _make_report(outcome_category="success", final_status="APPROVED")
        assert self._fn(report) is None

    def test_exception_no_po(self):
        from src.explanation import ExceptionExplanation
        report = _make_report(exception=ExceptionExplanation(
            reason="NO_PO", triggering_gateway="n8",
            node="n_exc_no_po", expected_status="EXCEPTION_NO_PO",
        ))
        result = self._fn(report)
        assert result["primary_issue"] == "Exception: NO_PO"
        assert "non-PO workflow" in result["review_focus"]

    def test_exception_bad_extraction(self):
        from src.explanation import ExceptionExplanation
        report = _make_report(
            final_status="EXCEPTION_BAD_EXTRACTION",
            exception=ExceptionExplanation(
                reason="BAD_EXTRACTION", triggering_gateway="n3",
                node="n_exc_bad", expected_status="EXCEPTION_BAD_EXTRACTION",
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Exception: BAD_EXTRACTION"
        assert "source text quality" in result["review_focus"]

    def test_extraction_failure(self):
        from src.explanation import ExtractionExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH", "PO_PATTERN_MISSING"),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Extraction verification failed"
        assert any("AMOUNT_MISMATCH" in s for s in result["supporting_signals"])
        assert "evidence anchors" in result["review_focus"]

    def test_arithmetic_failure(self):
        from src.explanation import ArithmeticExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Invoice arithmetic inconsistency"
        assert any("300.0" in s for s in result["supporting_signals"])
        assert "subtotal" in result["review_focus"]

    def test_match_no_match(self):
        from src.explanation import MatchExplanation
        report = _make_report(
            outcome_category="rejection", final_status="REJECTED",
            match=MatchExplanation(
                match_result="NO_MATCH", source_flag="po_match",
                po_match_input=False, match_3_way_input=None,
                resolved_from="po_match",
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Match result: NO_MATCH"
        assert "3-way match" in result["review_focus"]

    def test_priority_exception_over_arithmetic(self):
        from src.explanation import ArithmeticExplanation, ExceptionExplanation
        report = _make_report(
            exception=ExceptionExplanation(
                reason="NO_PO", triggering_gateway="n8",
                node="n_exc_no_po", expected_status="EXCEPTION_NO_PO",
            ),
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Exception: NO_PO"

    def test_priority_extraction_over_arithmetic(self):
        from src.explanation import ArithmeticExplanation, ExtractionExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH",),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Extraction verification failed"

    def test_fallback_outcome(self):
        report = _make_report(
            outcome_category="in_progress", final_status="NEW",
        )
        result = self._fn(report)
        assert result["primary_issue"] == "Outcome: in_progress"
        assert "structured audit sections" in result["review_focus"]

    def test_output_shape(self):
        from src.explanation import ExceptionExplanation
        report = _make_report(exception=ExceptionExplanation(
            reason="NO_PO", triggering_gateway="n8",
            node="n_exc_no_po", expected_status="EXCEPTION_NO_PO",
        ))
        result = self._fn(report)
        assert set(result.keys()) == {"primary_issue", "supporting_signals", "review_focus"}
        assert isinstance(result["supporting_signals"], list)
        assert len(result["supporting_signals"]) <= 4


# ===================================================================
# Failure drill-down panel
# ===================================================================

def _get_drilldown_fn():
    """Extract _build_failure_drilldown from app.py via AST."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "app.py"
    source_text = src.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_failure_drilldown":
            func_src = ast.get_source_segment(source_text, node)
            break
    else:
        raise RuntimeError("_build_failure_drilldown not found in app.py")
    ns: dict = {}
    exec(compile(func_src, str(src), "exec"), ns)
    return ns["_build_failure_drilldown"]


class TestFailureDrilldown:

    _fn = staticmethod(_get_drilldown_fn())

    def test_success_returns_none(self):
        report = _make_report(outcome_category="success", final_status="APPROVED")
        assert self._fn(report) is None

    def test_exception_drilldown_core_fields(self):
        from src.explanation import ExceptionExplanation
        report = _make_report(exception=ExceptionExplanation(
            reason="NO_PO", triggering_gateway="n8",
            node="n_exc_no_po", expected_status="EXCEPTION_NO_PO",
        ))
        result = self._fn(report)
        assert result["title"] == "Exception Details"
        labels = [r[0] for r in result["rows"]]
        assert "Reason" in labels
        assert "Node" in labels
        assert "Gateway" in labels
        assert "Expected status" in labels
        assert dict(result["rows"])["Reason"] == "NO_PO"

    def test_exception_drilldown_caps_rows(self):
        from src.explanation import (
            ArithmeticExplanation, ExceptionExplanation, ExtractionExplanation,
        )
        report = _make_report(
            exception=ExceptionExplanation(
                reason="BAD_EXTRACTION", triggering_gateway="n3",
                node="n_exc_bad", expected_status="EXCEPTION_BAD_EXTRACTION",
            ),
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH", "PO_PATTERN_MISSING"),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Exception Details"
        assert len(result["rows"]) <= 6

    def test_extraction_failure_drilldown(self):
        from src.explanation import ExtractionExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH",),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Extraction Failure Details"
        labels = [r[0] for r in result["rows"]]
        assert "Variant" in labels
        assert "Failure codes" in labels

    def test_extraction_failure_attempts(self):
        from src.explanation import ExtractionExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH",),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=2,
            ),
        )
        result = self._fn(report)
        row_dict = dict(result["rows"])
        assert row_dict.get("Extraction attempts") == "2"

    def test_arithmetic_failure_total_delta(self):
        from src.explanation import ArithmeticExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Arithmetic Failure Details"
        row_dict = dict(result["rows"])
        assert "300.0" in row_dict.get("Total delta", "")

    def test_arithmetic_failure_tax_delta_only(self):
        from src.explanation import ArithmeticExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            arithmetic=ArithmeticExplanation(
                checks_run=("tax_rate",), passed=False,
                failure_codes=("ARITH_TAX_RATE_MISMATCH",),
                total_sum_delta=None, tax_rate_delta=0.05, check_count=1,
            ),
        )
        result = self._fn(report)
        row_dict = dict(result["rows"])
        assert "Total delta" not in row_dict
        assert "0.05" in row_dict.get("Tax delta", "")

    def test_match_problem_drilldown(self):
        from src.explanation import MatchExplanation
        report = _make_report(
            outcome_category="rejection", final_status="REJECTED",
            match=MatchExplanation(
                match_result="NO_MATCH", source_flag="po_match",
                po_match_input=False, match_3_way_input=None,
                resolved_from="po_match",
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Match Details"
        row_dict = dict(result["rows"])
        assert row_dict["Match result"] == "NO_MATCH"
        assert row_dict["Source"] == "po_match"

    def test_priority_exception_over_extraction(self):
        from src.explanation import ExceptionExplanation, ExtractionExplanation
        report = _make_report(
            exception=ExceptionExplanation(
                reason="BAD_EXTRACTION", triggering_gateway="n3",
                node="n_exc_bad", expected_status="EXCEPTION_BAD_EXTRACTION",
            ),
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH",),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Exception Details"

    def test_priority_extraction_over_arithmetic(self):
        from src.explanation import ArithmeticExplanation, ExtractionExplanation
        report = _make_report(
            outcome_category="rejection", final_status="BAD_EXTRACTION",
            extraction=ExtractionExplanation(
                variant="verifier", valid=False,
                failure_codes=("AMOUNT_MISMATCH",),
                status_before="NEW", status_after="BAD_EXTRACTION",
                field_results=None, extraction_count=1,
            ),
            arithmetic=ArithmeticExplanation(
                checks_run=("total_sum",), passed=False,
                failure_codes=("ARITH_TOTAL_MISMATCH",),
                total_sum_delta=300.0, tax_rate_delta=None, check_count=1,
            ),
        )
        result = self._fn(report)
        assert result["title"] == "Extraction Failure Details"

    def test_fallback_drilldown(self):
        report = _make_report(
            outcome_category="in_progress", final_status="NEW",
        )
        result = self._fn(report)
        assert result["title"] == "Outcome Details"
        row_dict = dict(result["rows"])
        assert row_dict["Outcome category"] == "in_progress"
        assert row_dict["Final status"] == "NEW"

    def test_output_shape(self):
        from src.explanation import ExceptionExplanation
        report = _make_report(exception=ExceptionExplanation(
            reason="NO_PO", triggering_gateway="n8",
            node="n_exc_no_po", expected_status="EXCEPTION_NO_PO",
        ))
        result = self._fn(report)
        assert set(result.keys()) == {"title", "rows"}
        assert isinstance(result["rows"], list)
        for row in result["rows"]:
            assert isinstance(row, tuple)
            assert len(row) == 2
