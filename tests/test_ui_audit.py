"""
tests/test_ui_audit.py
Tests for the ui_audit.py pure-Python audit log parsers.

Covers:
- Safe handling of non-dict, non-JSON, and missing-key entries
- Correct extraction of the *last* matching event
- All four extractor functions
"""
from __future__ import annotations

import json

import pytest

from src.ui_audit import (
    extract_exception_event,
    extract_match_event,
    extract_router_events,
    extract_verifier_event,
    _try_parse,
)


# ---------------------------------------------------------------------------
# _try_parse internals
# ---------------------------------------------------------------------------
class TestTryParse:

    def test_dict_passthrough(self):
        assert _try_parse({"event": "test"}) == {"event": "test"}

    def test_json_string(self):
        s = json.dumps({"event": "test"})
        assert _try_parse(s) == {"event": "test"}

    def test_non_dict_json(self):
        assert _try_parse("[1, 2, 3]") is None

    def test_invalid_json_string(self):
        assert _try_parse("not json at all") is None

    def test_integer_ignored(self):
        assert _try_parse(42) is None

    def test_none_ignored(self):
        assert _try_parse(None) is None

    def test_bool_ignored(self):
        assert _try_parse(True) is None

    def test_empty_string(self):
        assert _try_parse("") is None

    def test_list_ignored(self):
        assert _try_parse([1, 2]) is None


# ---------------------------------------------------------------------------
# extract_exception_event
# ---------------------------------------------------------------------------
class TestExtractExceptionEvent:

    def test_returns_exception_station_event(self):
        log = [
            json.dumps({"node": "MATCH_3_WAY", "event": "match_result_set", "match_result": "MATCH"}),
            json.dumps({"node": "task:MANUAL_REVIEW_NO_ROUTE", "event": "exception_station", "reason": "NO_ROUTE"}),
        ]
        result = extract_exception_event(log)
        assert result is not None
        assert result["reason"] == "NO_ROUTE"
        assert result["event"] == "exception_station"

    def test_returns_most_recent(self):
        log = [
            json.dumps({"event": "exception_station", "reason": "AMBIGUOUS_ROUTE"}),
            json.dumps({"event": "exception_station", "reason": "NO_ROUTE"}),
        ]
        result = extract_exception_event(log)
        assert result["reason"] == "NO_ROUTE"

    def test_none_when_no_exception(self):
        log = [
            json.dumps({"event": "match_result_set", "match_result": "MATCH"}),
            "Executed APPROVE at n5",
        ]
        assert extract_exception_event(log) is None

    def test_empty_log(self):
        assert extract_exception_event([]) is None

    def test_ignores_non_dict_entries(self):
        log = [42, None, True, "plain string", [1, 2]]
        assert extract_exception_event(log) is None

    def test_ignores_missing_event_key(self):
        log = [json.dumps({"reason": "NO_ROUTE"})]
        assert extract_exception_event(log) is None


# ---------------------------------------------------------------------------
# extract_match_event
# ---------------------------------------------------------------------------
class TestExtractMatchEvent:

    def test_returns_match_result_set(self):
        log = [
            json.dumps({"node": "MATCH_3_WAY", "event": "match_result_set",
                         "match_result": "MATCH", "source_flag": "po_match"}),
        ]
        result = extract_match_event(log)
        assert result is not None
        assert result["match_result"] == "MATCH"
        assert result["source_flag"] == "po_match"

    def test_returns_most_recent(self):
        log = [
            json.dumps({"event": "match_result_set", "match_result": "UNKNOWN"}),
            json.dumps({"event": "match_result_set", "match_result": "MATCH"}),
        ]
        result = extract_match_event(log)
        assert result["match_result"] == "MATCH"

    def test_none_when_no_match_event(self):
        log = ["Executed APPROVE at n5"]
        assert extract_match_event(log) is None

    def test_empty_log(self):
        assert extract_match_event([]) is None

    def test_ignores_garbage(self):
        log = [42, None, "not json", {"event": "other"}]
        assert extract_match_event(log) is None


# ---------------------------------------------------------------------------
# extract_router_events
# ---------------------------------------------------------------------------
class TestExtractRouterEvents:

    def test_captures_executed_strings(self):
        log = [
            "Executed APPROVE [role_ap_clerk] at n5",
            "Executed MATCH_3_WAY at n4",
        ]
        result = extract_router_events(log)
        assert len(result) == 2
        assert result[0]["raw"].startswith("Executed APPROVE")

    def test_captures_route_events(self):
        log = [
            json.dumps({"event": "route_decision", "target": "n5"}),
        ]
        result = extract_router_events(log)
        assert len(result) == 1
        assert result[0]["event"] == "route_decision"

    def test_preserves_order(self):
        log = [
            "Executed STEP_1 at n1",
            "Executed STEP_2 at n2",
            "Executed STEP_3 at n3",
        ]
        result = extract_router_events(log)
        assert len(result) == 3
        assert "STEP_1" in result[0]["raw"]
        assert "STEP_3" in result[2]["raw"]

    def test_empty_log(self):
        assert extract_router_events([]) == []

    def test_ignores_non_route_json(self):
        log = [
            json.dumps({"event": "extraction", "valid": True}),
        ]
        assert extract_router_events(log) == []

    def test_ignores_garbage(self):
        log = [42, None, True, [1, 2]]
        assert extract_router_events(log) == []

    def test_plain_strings_without_executed_prefix_ignored(self):
        log = ["Some random log message", "Validation result: true"]
        assert extract_router_events(log) == []


# ---------------------------------------------------------------------------
# extract_verifier_event
# ---------------------------------------------------------------------------
class TestExtractVerifierEvent:

    def test_returns_extraction_event(self):
        log = [
            json.dumps({"node": "ENTER_RECORD", "event": "extraction",
                         "valid": True, "reasons": []}),
        ]
        result = extract_verifier_event(log)
        assert result is not None
        assert result["valid"] is True
        assert result["reasons"] == []

    def test_returns_verifier_event(self):
        log = [
            json.dumps({"event": "verifier", "valid": False,
                         "reasons": ["AMOUNT_MISMATCH"]}),
        ]
        result = extract_verifier_event(log)
        assert result is not None
        assert result["valid"] is False

    def test_returns_most_recent(self):
        log = [
            json.dumps({"event": "extraction", "valid": False, "reasons": ["ERROR"]}),
            json.dumps({"event": "extraction", "valid": True, "reasons": []}),
        ]
        result = extract_verifier_event(log)
        assert result["valid"] is True

    def test_none_when_no_verifier_event(self):
        log = ["Executed APPROVE at n5"]
        assert extract_verifier_event(log) is None

    def test_empty_log(self):
        assert extract_verifier_event([]) is None

    def test_ignores_garbage(self):
        log = [42, None, "bad json", [1]]
        assert extract_verifier_event(log) is None

    def test_ignores_missing_keys(self):
        """Event has no 'valid' or 'reasons' — still returned if event matches."""
        log = [json.dumps({"event": "extraction"})]
        result = extract_verifier_event(log)
        assert result is not None
        assert result.get("valid") is None


# ---------------------------------------------------------------------------
# Mixed realistic audit log
# ---------------------------------------------------------------------------
class TestMixedRealisticLog:
    """Integration-style test with a realistic audit_log from a full run."""

    @pytest.fixture
    def realistic_log(self):
        return [
            json.dumps({"node": "ENTER_RECORD", "event": "extraction",
                         "valid": True, "reasons": []}),
            "Validation result: {'is_valid': True}",
            "Executed MATCH_3_WAY [role_system] at n15",
            json.dumps({"node": "MATCH_3_WAY", "event": "match_result_set",
                         "match_result": "MATCH", "source_flag": "po_match"}),
            "Executed APPROVE [role_ap_clerk] at n5",
            "Executed SCHEDULE_PAYMENT at n6",
            "Executed EXECUTE_PAYMENT at n7",
        ]

    def test_verifier_from_realistic(self, realistic_log):
        v = extract_verifier_event(realistic_log)
        assert v is not None
        assert v["valid"] is True

    def test_match_from_realistic(self, realistic_log):
        m = extract_match_event(realistic_log)
        assert m is not None
        assert m["match_result"] == "MATCH"

    def test_exception_from_realistic(self, realistic_log):
        assert extract_exception_event(realistic_log) is None

    def test_router_events_from_realistic(self, realistic_log):
        routes = extract_router_events(realistic_log)
        assert len(routes) >= 3  # at least the Executed entries
