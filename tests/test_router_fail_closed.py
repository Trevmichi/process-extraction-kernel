"""
tests/test_router_fail_closed.py
Tests for Phase 3: Router Hardening & Unmodeled Reservoir.

Covers:
- Strict 2-phase routing: conditional first, unconditional only if 0 cond matches
- 0 matches → NO_ROUTE exception station
- >1 conditional matches → AMBIGUOUS_ROUTE exception station
- >1 unconditional edges → AMBIGUOUS_ROUTE exception station
- Unmodeled JSONL logging on NO_ROUTE and AMBIGUOUS_ROUTE
- RouterError raised when station_map is None (backward compat)
- Trivial short-circuits (single edge, all-same-target) still work
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.agent.router import route_edge, RouterError, _AMBIGUOUS_INTENT, _NO_ROUTE_INTENT
from src.unmodeled import record_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(**overrides) -> dict:
    base = {
        "invoice_id": "INV-TEST",
        "vendor": "Acme",
        "amount": 500.0,
        "has_po": True,
        "po_match": True,
        "match_3_way": True,
        "status": "NEW",
        "current_node": "n1",
        "audit_log": [],
        "raw_text": "",
        "extraction": {},
        "provenance": {},
    }
    base.update(overrides)
    return base


def _node(node_id: str = "n1", **meta_overrides) -> dict:
    meta = {"canonical_key": f"gw:{node_id}", "intent_key": f"gw:{node_id}"}
    meta.update(meta_overrides)
    return {"id": node_id, "kind": "gateway", "decision": {}, "action": None, "meta": meta}


_STATION_MAP = {
    _AMBIGUOUS_INTENT: "n_exc_ambiguous_route",
    _NO_ROUTE_INTENT: "n_exc_no_route",
}


# ===================================================================
# Test: Trivial short-circuits (preserved from original router)
# ===================================================================
class TestTrivialShortCircuits:

    def test_single_edge(self):
        edges = [{"frm": "n1", "to": "n2", "condition": None}]
        assert route_edge(_state(), edges, _node()) == "n2"

    def test_all_same_target(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
        ]
        assert route_edge(_state(), edges, _node()) == "n2"

    def test_no_edges_raises(self):
        with pytest.raises(RouterError):
            route_edge(_state(), [], _node())


# ===================================================================
# Test: Phase 1 — Conditional edge evaluation
# ===================================================================
class TestPhase1Conditional:

    def test_single_conditional_match(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "has_po == false"},
        ]
        result = route_edge(_state(has_po=True), edges, _node(), _STATION_MAP)
        assert result == "n2"

    def test_single_conditional_match_second(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "has_po == false"},
        ]
        result = route_edge(_state(has_po=False), edges, _node(), _STATION_MAP)
        assert result == "n3"

    def test_conditional_with_unconditional_fallback(self):
        """When a conditional matches, unconditional is never considered."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": None},
        ]
        result = route_edge(_state(has_po=True), edges, _node(), _STATION_MAP)
        assert result == "n2"

    def test_no_conditional_match_falls_to_unconditional(self):
        """When no conditional matches, the single unconditional is taken."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": None},
        ]
        result = route_edge(_state(has_po=False), edges, _node(), _STATION_MAP)
        assert result == "n3"


# ===================================================================
# Test: AMBIGUOUS_ROUTE — >1 conditional match
# ===================================================================
class TestAmbiguousRoute:

    def test_multiple_conditional_matches_routes_to_station(self):
        """Both conditions are true → AMBIGUOUS_ROUTE station."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "amount > 100"},
        ]
        state = _state(has_po=True, amount=500.0)
        result = route_edge(state, edges, _node(), _STATION_MAP)
        assert result == "n_exc_ambiguous_route"

    def test_multiple_unconditional_routes_to_station(self):
        """No conditionals, 2 unconditional edges → AMBIGUOUS_ROUTE."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": None},
            {"frm": "n1", "to": "n3", "condition": None},
        ]
        result = route_edge(_state(), edges, _node(), _STATION_MAP)
        assert result == "n_exc_ambiguous_route"

    def test_ambiguous_without_station_map_raises(self):
        """Without station_map, ambiguous raises RouterError."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "amount > 100"},
        ]
        with pytest.raises(RouterError, match="ambiguous"):
            route_edge(_state(has_po=True, amount=500.0), edges, _node())


# ===================================================================
# Test: NO_ROUTE — 0 matches in both phases
# ===================================================================
class TestNoRoute:

    def test_no_match_routes_to_station(self):
        """All conditionals fail, no unconditional → NO_ROUTE station."""
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 9999"},
        ]
        state = _state(has_po=True, amount=500.0)
        result = route_edge(state, edges, _node(), _STATION_MAP)
        assert result == "n_exc_no_route"

    def test_no_match_without_station_map_raises(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 9999"},
        ]
        with pytest.raises(RouterError, match="no_route"):
            route_edge(_state(has_po=True, amount=500.0), edges, _node())


# ===================================================================
# Test: Station lookup errors
# ===================================================================
class TestStationLookupErrors:

    def test_missing_ambiguous_station_raises_valueerror(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "amount > 100"},
        ]
        incomplete_map = {_NO_ROUTE_INTENT: "n_exc_no_route"}
        with pytest.raises(ValueError, match="AMBIGUOUS_ROUTE"):
            route_edge(_state(has_po=True, amount=500.0), edges, _node(), incomplete_map)

    def test_missing_no_route_station_raises_valueerror(self):
        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 99999"},
        ]
        incomplete_map = {_AMBIGUOUS_INTENT: "n_exc_ambiguous_route"}
        with pytest.raises(ValueError, match="NO_ROUTE"):
            route_edge(_state(has_po=True, amount=1.0), edges, _node(), incomplete_map)


# ===================================================================
# Test: Unmodeled JSONL logging
# ===================================================================
class TestUnmodeledLogging:

    def test_record_event_writes_jsonl(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        record_event({"reason": "TEST", "from_node": "n1"}, path=path)
        record_event({"reason": "TEST2", "from_node": "n2"}, path=path)

        lines = (tmp_path / "test.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["reason"] == "TEST"
        assert json.loads(lines[1])["reason"] == "TEST2"

    def test_ambiguous_route_logs_event(self, tmp_path, monkeypatch):
        path = str(tmp_path / "unmodeled.jsonl")
        monkeypatch.setattr("src.agent.router.record_event",
                            lambda event, **kw: record_event(event, path=path))

        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            {"frm": "n1", "to": "n3", "condition": "amount > 100"},
        ]
        route_edge(_state(has_po=True, amount=500.0), edges, _node(), _STATION_MAP)

        lines = (tmp_path / "unmodeled.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["reason"] == "AMBIGUOUS_ROUTE"
        assert entry["from_node"] == "n1"
        assert "matched_targets" in entry
        assert "raw_text" not in entry  # privacy

    def test_no_route_logs_event(self, tmp_path, monkeypatch):
        path = str(tmp_path / "unmodeled.jsonl")
        monkeypatch.setattr("src.agent.router.record_event",
                            lambda event, **kw: record_event(event, path=path))

        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 99999"},
        ]
        route_edge(_state(has_po=True, amount=1.0), edges, _node(), _STATION_MAP)

        lines = (tmp_path / "unmodeled.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["reason"] == "NO_ROUTE"
        assert entry["from_node"] == "n1"
        assert "matched_targets" not in entry
        assert "raw_text" not in entry

    def test_no_raw_text_in_event(self, tmp_path, monkeypatch):
        """Privacy: raw invoice text must never appear in logged events."""
        path = str(tmp_path / "unmodeled.jsonl")
        monkeypatch.setattr("src.agent.router.record_event",
                            lambda event, **kw: record_event(event, path=path))

        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 99999"},
        ]
        state = _state(has_po=True, amount=1.0,
                       raw_text="INVOICE #123 From: Secret Corp Total: $99")
        route_edge(state, edges, _node(), _STATION_MAP)

        content = (tmp_path / "unmodeled.jsonl").read_text()
        assert "Secret Corp" not in content
        assert "INVOICE #123" not in content

    def test_event_contains_structural_metadata(self, tmp_path, monkeypatch):
        path = str(tmp_path / "unmodeled.jsonl")
        monkeypatch.setattr("src.agent.router.record_event",
                            lambda event, **kw: record_event(event, path=path))

        edges = [
            {"frm": "n1", "to": "n2", "condition": "has_po == false"},
            {"frm": "n1", "to": "n3", "condition": "amount > 99999"},
        ]
        state = _state(has_po=True, amount=1.0, invoice_id="INV-777")
        route_edge(state, edges, _node(), _STATION_MAP)

        entry = json.loads((tmp_path / "unmodeled.jsonl").read_text().strip())
        assert entry["process_id"] == "INV-777"
        assert entry["from_node"] == "n1"
        assert "state_keys_present" in entry
        assert isinstance(entry["state_keys_present"], list)


# ===================================================================
# Test: Phase precedence — conditional wins over unconditional
# ===================================================================
class TestPhasePrecedence:

    def test_conditional_match_ignores_unconditional(self):
        """Even with an unconditional edge, a matching conditional wins."""
        edges = [
            {"frm": "n1", "to": "n_fallback", "condition": None},
            {"frm": "n1", "to": "n_correct", "condition": "has_po == true"},
        ]
        result = route_edge(_state(has_po=True), edges, _node(), _STATION_MAP)
        assert result == "n_correct"

    def test_no_conditional_match_takes_unconditional(self):
        edges = [
            {"frm": "n1", "to": "n_fallback", "condition": None},
            {"frm": "n1", "to": "n_wrong", "condition": "has_po == false"},
        ]
        result = route_edge(_state(has_po=True), edges, _node(), _STATION_MAP)
        assert result == "n_fallback"
