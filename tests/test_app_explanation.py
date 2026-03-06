"""
tests/test_app_explanation.py
Parity tests proving ExplanationReport fields match ui_audit extractor
results for representative audit_logs.  These verify that the app.py
data-source swap (Phase 7) produces identical behavior.
"""
from __future__ import annotations

import json

from src.audit_parser import parse_audit_log
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
