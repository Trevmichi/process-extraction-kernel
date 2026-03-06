"""
tests/test_audit_parser.py
Comprehensive tests for the canonical audit parser.

Covers:
- Per-event-type parsing (well-formed + edge cases)
- ParsedAuditLog category accessors and last_* convenience properties
- Cross-validation against ui_audit.py extractors
- Defensive handling of malformed/unknown entries
- Realistic end-to-end integration
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audit_parser import (
    AmountCandidatesEvent,
    CriticRetryEvent,
    ExceptionStationEvent,
    ExtractionEvent,
    MatchInputsEvent,
    MatchResultSetEvent,
    ParsedAuditLog,
    PlainTextEntry,
    RouteDecisionEvent,
    RouteRecordEvent,
    RouteStepEntry,
    SequentialDispatchEvent,
    UnknownJsonEntry,
    VerifierSummaryEvent,
    parse_audit_log,
)


# ===================================================================
# Helpers
# ===================================================================

def _j(obj: dict) -> str:
    """Shorthand for json.dumps."""
    return json.dumps(obj)


# ===================================================================
# Empty / basic
# ===================================================================

class TestParseAuditLogBasics:

    def test_empty_log(self):
        parsed = parse_audit_log([])
        assert parsed.entries == ()
        assert parsed.route_decisions == ()
        assert parsed.last_exception is None
        assert parsed.last_extraction is None
        assert parsed.last_match is None
        assert parsed.last_verifier_summary is None

    def test_single_plain_text(self):
        parsed = parse_audit_log(["some random text"])
        assert len(parsed.entries) == 1
        assert isinstance(parsed.entries[0], PlainTextEntry)
        assert parsed.entries[0].raw == "some random text"
        assert len(parsed.plain_text) == 1

    def test_single_json_event(self):
        log = [_j({"event": "exception_station", "node": "n1",
                    "reason": "BAD_EXTRACTION", "gateway": "n3"})]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 1
        assert isinstance(parsed.entries[0], ExceptionStationEvent)
        assert len(parsed.exception_events) == 1

    def test_order_preserved(self):
        log = [
            _j({"event": "route_decision", "from_node": "n1",
                 "candidates": [], "selected": "n2", "reason": "single_edge"}),
            "Executed APPROVE [clerk] at n5",
            _j({"event": "exception_station", "node": "n_exc",
                 "reason": "NO_PO", "gateway": "n3"}),
        ]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 3
        assert isinstance(parsed.entries[0], RouteDecisionEvent)
        assert isinstance(parsed.entries[1], RouteStepEntry)
        assert isinstance(parsed.entries[2], ExceptionStationEvent)


# ===================================================================
# RouteDecisionEvent
# ===================================================================

class TestRouteDecisionEvent:

    def test_well_formed(self):
        log = [_j({"event": "route_decision", "from_node": "n3",
                    "candidates": [{"to": "n4", "condition": "has_po == true",
                                    "matched": True}],
                    "selected": "n4", "reason": "condition_match"})]
        parsed = parse_audit_log(log)
        e = parsed.route_decisions[0]
        assert e.from_node == "n3"
        assert e.selected == "n4"
        assert e.reason == "condition_match"
        assert len(e.candidates) == 1
        assert e.candidates[0]["to"] == "n4"

    def test_null_selected(self):
        log = [_j({"event": "route_decision", "from_node": "n10",
                    "candidates": [], "selected": None, "reason": "no_route"})]
        e = parse_audit_log(log).route_decisions[0]
        assert e.selected is None

    def test_missing_fields_defaults(self):
        log = [_j({"event": "route_decision"})]
        e = parse_audit_log(log).route_decisions[0]
        assert e.from_node == ""
        assert e.candidates == ()
        assert e.selected is None
        assert e.reason == ""


# ===================================================================
# ExtractionEvent
# ===================================================================

class TestExtractionEvent:

    def test_variant_llm_error(self):
        log = [_j({"node": "ENTER_RECORD", "event": "extraction",
                    "valid": False, "reasons": ["LLM_ERROR"]})]
        e = parse_audit_log(log).extraction_events[0]
        assert e.valid is False
        assert e.reasons == ("LLM_ERROR",)
        assert e.failure_codes is None
        assert e.variant == "llm_error"

    def test_variant_structural(self):
        log = [_j({"node": "ENTER_RECORD", "event": "extraction",
                    "valid": False, "failure_codes": ["STRUCT_MISSING_KEY"],
                    "status": "BAD_EXTRACTION"})]
        e = parse_audit_log(log).extraction_events[0]
        assert e.failure_codes == ("STRUCT_MISSING_KEY",)
        assert e.reasons is None
        assert e.status == "BAD_EXTRACTION"
        assert e.variant == "structural"

    def test_variant_verifier_valid(self):
        log = [_j({"node": "ENTER_RECORD", "event": "extraction",
                    "valid": True, "reasons": []})]
        e = parse_audit_log(log).extraction_events[0]
        assert e.valid is True
        assert e.reasons == ()
        assert e.variant == "verifier"

    def test_variant_verifier_failure(self):
        log = [_j({"node": "ENTER_RECORD", "event": "extraction",
                    "valid": False, "reasons": ["AMOUNT_MISMATCH"]})]
        e = parse_audit_log(log).extraction_events[0]
        assert e.variant == "verifier"
        assert e.reasons == ("AMOUNT_MISMATCH",)

    def test_missing_fields_defaults(self):
        log = [_j({"event": "extraction"})]
        e = parse_audit_log(log).extraction_events[0]
        assert e.node == ""
        assert e.valid is False
        assert e.reasons is None
        assert e.failure_codes is None
        assert e.status is None


# ===================================================================
# ExceptionStationEvent
# ===================================================================

class TestExceptionStationEvent:

    def test_all_reasons(self):
        reasons = ["BAD_EXTRACTION", "UNMODELED_GATE", "AMBIGUOUS_ROUTE",
                    "NO_ROUTE", "NO_PO", "MATCH_FAILED", "UNKNOWN"]
        for r in reasons:
            log = [_j({"event": "exception_station", "node": "n_exc",
                        "reason": r, "gateway": "n3"})]
            e = parse_audit_log(log).exception_events[0]
            assert e.reason == r

    def test_gateway_preserved(self):
        log = [_j({"event": "exception_station", "node": "n_exc",
                    "reason": "NO_PO", "gateway": "?"})]
        e = parse_audit_log(log).exception_events[0]
        assert e.gateway == "?"


# ===================================================================
# MatchResultSetEvent
# ===================================================================

class TestMatchResultSetEvent:

    def test_all_match_results(self):
        for mr in ["MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"]:
            log = [_j({"event": "match_result_set", "node": "MATCH_3_WAY",
                        "match_result": mr, "source_flag": "po_match"})]
            e = parse_audit_log(log).match_events[0]
            assert e.match_result == mr

    def test_null_source_flag(self):
        log = [_j({"event": "match_result_set", "node": "MATCH_3_WAY",
                    "match_result": "UNKNOWN", "source_flag": None})]
        e = parse_audit_log(log).match_events[0]
        assert e.source_flag is None


# ===================================================================
# VerifierSummaryEvent
# ===================================================================

class TestVerifierSummaryEvent:

    def test_full_event(self):
        log = [_j({"event": "verifier_summary", "valid": True,
                    "failure_codes": [],
                    "status_before": "NEW", "status_after": "DATA_EXTRACTED",
                    "vendor": {"value": "Acme", "ok": True, "has_evidence": True},
                    "amount": {"value": 100.0, "ok": True, "has_evidence": True,
                               "parsed_evidence": 100.0, "delta": 0.0},
                    "has_po": {"value": True, "ok": True, "has_evidence": True}})]
        e = parse_audit_log(log).verifier_summaries[0]
        assert e.valid is True
        assert e.failure_codes == ()
        assert e.vendor["value"] == "Acme"
        assert e.amount["delta"] == 0.0

    def test_failure_codes_populated(self):
        log = [_j({"event": "verifier_summary", "valid": False,
                    "failure_codes": ["AMOUNT_MISMATCH"],
                    "status_before": "NEW", "status_after": "NEEDS_RETRY",
                    "vendor": {}, "amount": {}, "has_po": {}})]
        e = parse_audit_log(log).verifier_summaries[0]
        assert e.failure_codes == ("AMOUNT_MISMATCH",)
        assert e.status_after == "NEEDS_RETRY"

    def test_missing_nested_defaults_to_empty_dict(self):
        log = [_j({"event": "verifier_summary"})]
        e = parse_audit_log(log).verifier_summaries[0]
        assert e.vendor == {}
        assert e.amount == {}
        assert e.has_po == {}


# ===================================================================
# CriticRetryEvent
# ===================================================================

class TestCriticRetryEvent:

    def test_llm_error_variant(self):
        log = [_j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                    "attempt": 1, "valid": False,
                    "failure_codes": ["LLM_ERROR"], "status": "BAD_EXTRACTION"})]
        e = parse_audit_log(log).critic_retries[0]
        assert e.attempt == 1
        assert e.failure_codes == ("LLM_ERROR",)

    def test_verifier_success_variant(self):
        log = [_j({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                    "attempt": 2, "valid": True,
                    "failure_codes": [], "status": "DATA_EXTRACTED"})]
        e = parse_audit_log(log).critic_retries[0]
        assert e.valid is True
        assert e.status == "DATA_EXTRACTED"

    def test_missing_attempt_defaults(self):
        log = [_j({"event": "critic_retry_executed"})]
        e = parse_audit_log(log).critic_retries[0]
        assert e.attempt == 0


# ===================================================================
# Non-schema events
# ===================================================================

class TestRouteRecordEvent:

    def test_wraps_dict(self):
        rr = {"gateway_id": "n8", "schema_version": "route_record_v1"}
        log = [_j({"event": "route_record", "route_record": rr})]
        e = parse_audit_log(log).route_records[0]
        assert e.route_record["gateway_id"] == "n8"

    def test_missing_route_record(self):
        log = [_j({"event": "route_record"})]
        e = parse_audit_log(log).route_records[0]
        assert e.route_record == {}


class TestMatchInputsEvent:

    def test_well_formed(self):
        log = [_j({"event": "match_inputs", "node": "MATCH_3_WAY",
                    "po_match": True, "match_3_way": False})]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, MatchInputsEvent)
        assert e.po_match is True
        assert e.match_3_way is False

    def test_null_fields(self):
        log = [_j({"event": "match_inputs", "node": "MATCH_3_WAY"})]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, MatchInputsEvent)
        assert e.po_match is None


class TestAmountCandidatesEvent:

    def test_with_candidates(self):
        log = [_j({"event": "amount_candidates",
                    "candidates": [{"raw": "100", "parsed": 100.0}],
                    "selected": 100.0, "winning_keyword": "total"})]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, AmountCandidatesEvent)
        assert len(e.candidates) == 1
        assert e.selected == 100.0

    def test_empty_candidates(self):
        log = [_j({"event": "amount_candidates", "candidates": [],
                    "selected": None, "winning_keyword": None})]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, AmountCandidatesEvent)
        assert e.candidates == ()


class TestSequentialDispatchEvent:

    def test_well_formed(self):
        log = [_j({"event": "sequential_dispatch", "node": "n10",
                    "chain": ["n11", "n12", "n13"]})]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, SequentialDispatchEvent)
        assert e.chain == ("n11", "n12", "n13")


# ===================================================================
# Plain text classification
# ===================================================================

class TestPlainTextClassification:

    def test_route_step_with_actor(self):
        log = ["Executed APPROVE [role_ap_clerk] at n5"]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, RouteStepEntry)
        assert e.intent == "APPROVE"
        assert e.actor == "role_ap_clerk"
        assert e.node_id == "n5"
        assert e.raw == "Executed APPROVE [role_ap_clerk] at n5"

    def test_route_step_without_actor(self):
        log = ["Executed MATCH_3_WAY at n4"]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, RouteStepEntry)
        assert e.intent == "MATCH_3_WAY"
        assert e.actor is None
        assert e.node_id == "n4"

    def test_validation_result_is_plain_text(self):
        log = ["Validation result: {'is_valid': True}"]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, PlainTextEntry)
        assert "Validation result" in e.raw

    def test_arbitrary_string_is_plain_text(self):
        log = ["something completely unstructured"]
        e = parse_audit_log(log).entries[0]
        assert isinstance(e, PlainTextEntry)

    def test_route_step_not_in_plain_text_tuple(self):
        """RouteStepEntry should NOT appear in plain_text accessor."""
        log = ["Executed APPROVE [clerk] at n5"]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 1
        assert len(parsed.plain_text) == 0


# ===================================================================
# Unknown JSON
# ===================================================================

class TestUnknownJsonEntry:

    def test_unrecognized_event(self):
        log = [_j({"event": "future_event", "data": 42})]
        parsed = parse_audit_log(log)
        assert len(parsed.unknown_json) == 1
        assert parsed.unknown_json[0].event == "future_event"
        assert parsed.unknown_json[0].raw["data"] == 42

    def test_no_event_key(self):
        log = [_j({"foo": "bar"})]
        parsed = parse_audit_log(log)
        assert len(parsed.unknown_json) == 1
        assert parsed.unknown_json[0].event is None

    def test_json_array_skipped(self):
        """JSON arrays (non-dict) are not entries — silently skipped."""
        log = ["[1, 2, 3]"]
        parsed = parse_audit_log(log)
        # json.loads succeeds but result is list, not dict → plain text
        assert len(parsed.entries) == 1
        assert isinstance(parsed.entries[0], PlainTextEntry)


# ===================================================================
# Defensive handling
# ===================================================================

class TestDefensiveHandling:

    def test_non_string_entries_skipped(self):
        log = [42, None, True, [1, 2]]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 0

    def test_malformed_json_becomes_plain_text(self):
        log = ["{not json at all}"]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 1
        assert isinstance(parsed.entries[0], PlainTextEntry)

    def test_empty_string(self):
        log = [""]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 1
        assert isinstance(parsed.entries[0], PlainTextEntry)

    def test_dict_entry_accepted(self):
        """Dicts (not JSON strings) should also be parsed."""
        log = [{"event": "exception_station", "node": "n1",
                "reason": "NO_PO", "gateway": "n3"}]
        parsed = parse_audit_log(log)
        assert len(parsed.exception_events) == 1

    def test_mixed_types_robust(self):
        log = [
            42,
            _j({"event": "extraction", "node": "ENTER_RECORD",
                 "valid": True, "reasons": []}),
            None,
            "Executed APPROVE [clerk] at n5",
            True,
        ]
        parsed = parse_audit_log(log)
        assert len(parsed.entries) == 2
        assert isinstance(parsed.entries[0], ExtractionEvent)
        assert isinstance(parsed.entries[1], RouteStepEntry)


# ===================================================================
# ParsedAuditLog accessors
# ===================================================================

class TestParsedAuditLogAccessors:

    def test_last_exception(self):
        log = [
            _j({"event": "exception_station", "node": "n1",
                 "reason": "BAD_EXTRACTION", "gateway": "n3"}),
            _j({"event": "exception_station", "node": "n2",
                 "reason": "NO_PO", "gateway": "n8"}),
        ]
        parsed = parse_audit_log(log)
        assert parsed.last_exception is not None
        assert parsed.last_exception.reason == "NO_PO"

    def test_last_extraction(self):
        log = [
            _j({"event": "extraction", "node": "ENTER_RECORD",
                 "valid": False, "reasons": ["AMOUNT_MISMATCH"]}),
            _j({"event": "extraction", "node": "ENTER_RECORD",
                 "valid": True, "reasons": []}),
        ]
        parsed = parse_audit_log(log)
        assert parsed.last_extraction is not None
        assert parsed.last_extraction.valid is True

    def test_last_match(self):
        log = [_j({"event": "match_result_set", "node": "MATCH_3_WAY",
                    "match_result": "MATCH", "source_flag": "po_match"})]
        parsed = parse_audit_log(log)
        assert parsed.last_match is not None
        assert parsed.last_match.match_result == "MATCH"

    def test_last_verifier_summary(self):
        log = [_j({"event": "verifier_summary", "valid": True,
                    "failure_codes": [], "status_before": "NEW",
                    "status_after": "DATA_EXTRACTED",
                    "vendor": {}, "amount": {}, "has_po": {}})]
        parsed = parse_audit_log(log)
        assert parsed.last_verifier_summary is not None
        assert parsed.last_verifier_summary.valid is True

    def test_last_accessors_none_when_empty(self):
        parsed = parse_audit_log([])
        assert parsed.last_exception is None
        assert parsed.last_extraction is None
        assert parsed.last_match is None
        assert parsed.last_verifier_summary is None

    def test_frozen(self):
        parsed = parse_audit_log([])
        with pytest.raises(AttributeError):
            parsed.entries = ()  # type: ignore[misc]


# ===================================================================
# Cross-validation vs ui_audit
# ===================================================================

class TestCrossValidationWithUiAudit:
    """Verify that ParsedAuditLog last_* accessors agree with ui_audit."""

    @pytest.fixture
    def realistic_log(self):
        return [
            _j({"event": "route_decision", "from_node": "n3",
                 "candidates": [{"to": "n4", "condition": "has_po == true",
                                 "matched": True}],
                 "selected": "n4", "reason": "condition_match"}),
            _j({"node": "ENTER_RECORD", "event": "extraction",
                 "valid": True, "reasons": []}),
            _j({"event": "verifier_summary", "valid": True,
                 "failure_codes": [], "status_before": "NEW",
                 "status_after": "DATA_EXTRACTED",
                 "vendor": {"value": "Acme", "ok": True, "has_evidence": True},
                 "amount": {"value": 100.0, "ok": True, "has_evidence": True,
                            "parsed_evidence": 100.0, "delta": 0.0},
                 "has_po": {"value": True, "ok": True, "has_evidence": True}}),
            _j({"event": "amount_candidates", "candidates": [],
                 "selected": None, "winning_keyword": None}),
            _j({"event": "match_inputs", "node": "MATCH_3_WAY",
                 "po_match": True, "match_3_way": False}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY",
                 "match_result": "MATCH", "source_flag": "po_match"}),
            _j({"event": "route_decision", "from_node": "n10",
                 "candidates": [], "selected": "n11",
                 "reason": "single_edge"}),
            "Executed APPROVE [role_ap_clerk] at n5",
        ]

    def test_last_extraction_matches_ui_audit(self, realistic_log):
        from src.ui_audit import extract_verifier_event
        parsed = parse_audit_log(realistic_log)
        ui_result = extract_verifier_event(realistic_log)

        assert ui_result is not None
        assert parsed.last_extraction is not None
        assert parsed.last_extraction.event == ui_result["event"]
        assert parsed.last_extraction.valid == ui_result["valid"]

    def test_last_match_matches_ui_audit(self, realistic_log):
        from src.ui_audit import extract_match_event
        parsed = parse_audit_log(realistic_log)
        ui_result = extract_match_event(realistic_log)

        assert ui_result is not None
        assert parsed.last_match is not None
        assert parsed.last_match.match_result == ui_result["match_result"]
        assert parsed.last_match.source_flag == ui_result["source_flag"]

    def test_no_exception_matches_ui_audit(self, realistic_log):
        """No exception in happy-path log — both should return None."""
        from src.ui_audit import extract_exception_event
        parsed = parse_audit_log(realistic_log)
        ui_result = extract_exception_event(realistic_log)

        assert ui_result is None
        assert parsed.last_exception is None

    def test_route_decisions_match_ui_audit(self, realistic_log):
        from src.ui_audit import extract_router_events
        parsed = parse_audit_log(realistic_log)
        ui_results = extract_router_events(realistic_log)

        # ui_audit returns route_decision + route_record + "Executed" entries
        ui_route_decisions = [r for r in ui_results
                              if r.get("event") == "route_decision"]
        assert len(parsed.route_decisions) == len(ui_route_decisions)
        for p, u in zip(parsed.route_decisions, ui_route_decisions):
            assert p.from_node == u["from_node"]
            assert p.reason == u["reason"]


# ===================================================================
# Realistic integration
# ===================================================================

class TestRealisticIntegration:

    def test_happy_path_invoice(self):
        """Simulate a complete happy-path invoice audit log."""
        log = [
            # Gateway routing (has_po check)
            _j({"event": "route_decision", "from_node": "n3",
                 "candidates": [
                     {"to": "n4", "condition": "has_po == true", "matched": True},
                     {"to": "n5", "condition": "has_po == false", "matched": False},
                 ],
                 "selected": "n4", "reason": "condition_match"}),
            _j({"event": "route_record", "route_record": {
                "gateway_id": "n3", "reason": "condition_match",
                "schema_version": "route_record_v1"}}),
            # Extraction
            _j({"node": "ENTER_RECORD", "event": "extraction",
                 "valid": True, "reasons": []}),
            _j({"event": "verifier_summary", "valid": True,
                 "failure_codes": [], "status_before": "NEW",
                 "status_after": "DATA_EXTRACTED",
                 "vendor": {"value": "Acme Corp", "ok": True, "has_evidence": True},
                 "amount": {"value": 1500.0, "ok": True, "has_evidence": True,
                            "parsed_evidence": 1500.0, "delta": 0.0},
                 "has_po": {"value": True, "ok": True, "has_evidence": True}}),
            _j({"event": "amount_candidates", "candidates": [
                {"raw": "1500.00", "parsed": 1500.0, "keyword": "total"}],
                 "selected": 1500.0, "winning_keyword": "total"}),
            # Match
            _j({"event": "match_inputs", "node": "MATCH_3_WAY",
                 "po_match": True, "match_3_way": False}),
            _j({"event": "match_result_set", "node": "MATCH_3_WAY",
                 "match_result": "MATCH", "source_flag": "po_match"}),
            # Approval routing
            _j({"event": "route_decision", "from_node": "n10",
                 "candidates": [{"to": "n11", "condition": None,
                                 "matched": None}],
                 "selected": "n11", "reason": "single_edge"}),
            "Executed APPROVE [role_ap_manager] at n11",
        ]

        parsed = parse_audit_log(log)

        # All entries present
        assert len(parsed.entries) == 9

        # Category counts
        assert len(parsed.route_decisions) == 2
        assert len(parsed.route_records) == 1
        assert len(parsed.extraction_events) == 1
        assert len(parsed.verifier_summaries) == 1
        assert len(parsed.match_events) == 1

        # Convenience accessors
        assert parsed.last_extraction is not None
        assert parsed.last_extraction.valid is True
        assert parsed.last_match is not None
        assert parsed.last_match.match_result == "MATCH"
        assert parsed.last_exception is None
        assert parsed.last_verifier_summary is not None
        assert parsed.last_verifier_summary.status_after == "DATA_EXTRACTED"

        # Route step parsed
        step = [e for e in parsed.entries if isinstance(e, RouteStepEntry)]
        assert len(step) == 1
        assert step[0].intent == "APPROVE"
        assert step[0].actor == "role_ap_manager"

        # No unknowns
        assert len(parsed.unknown_json) == 0
        assert len(parsed.plain_text) == 0
