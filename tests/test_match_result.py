"""
tests/test_match_result.py
Tests for Phase 4: Match Semantics Cleanup.

Covers:
- MatchResult Literal type definition
- Deterministic MATCH_3_WAY resolver (po_match > match_3_way > None)
- source_flag logging in audit_log
- Condition normalization for match_result labels
- Normalizer guardrail: inject match_result == "UNKNOWN" edge
- ValueError when UNMODELED_GATE station is missing
"""
from __future__ import annotations

import copy
import json

import pytest

from src.agent.state import MatchResult
from src.agent.nodes import execute_node
from src.conditions import normalize_condition, get_predicate, _PREDICATE_CACHE
from src.normalize_graph import inject_match_result_unknown_guardrail


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
        "match_result": "UNKNOWN",
        "status": "VALIDATED",
        "current_node": "n4",
        "audit_log": [],
        "raw_text": "",
        "extraction": {},
        "provenance": {},
    }
    base.update(overrides)
    return base


def _match3way_node(node_id: str = "n4") -> dict:
    return {
        "id": node_id,
        "kind": "task",
        "name": "3-Way Match",
        "action": {
            "type": "MATCH_3_WAY",
            "actor_id": "role_system",
            "artifact_id": "art_invoice",
            "extra": {},
        },
        "decision": None,
        "meta": {"canonical_key": f"task:MATCH_3_WAY@{node_id}"},
    }


def _graph_with_match_result_gw(include_unknown: bool = False,
                                 include_station: bool = True) -> dict:
    """Graph with a gateway that uses match_result conditions."""
    nodes = [
        {"id": "n1", "kind": "gateway", "meta": {"canonical_key": "gw:MATCH_3_WAY"}},
        {"id": "n2", "kind": "task", "meta": {"canonical_key": "task:APPROVE"}},
        {"id": "n3", "kind": "task", "meta": {"canonical_key": "task:REJECT"}},
    ]
    if include_station:
        nodes.append({
            "id": "n_exc_unmodeled",
            "kind": "task",
            "meta": {
                "canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc_unmodeled",
                "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE",
            },
        })
    edges = [
        {"frm": "n1", "to": "n2", "condition": 'match_result == "MATCH"'},
        {"frm": "n1", "to": "n3", "condition": 'match_result == "NO_MATCH"'},
    ]
    if include_unknown:
        target = "n_exc_unmodeled" if include_station else "n_missing"
        edges.append({
            "frm": "n1", "to": target,
            "condition": 'match_result == "UNKNOWN"',
        })
    return {"nodes": nodes, "edges": edges, "artifacts": []}


# ===================================================================
# Test: MatchResult Literal type
# ===================================================================
class TestMatchResultType:

    def test_literal_values(self):
        """MatchResult accepts exactly 4 values."""
        valid: list[MatchResult] = ["MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"]
        assert len(valid) == 4

    def test_type_is_literal(self):
        from typing import get_args
        args = get_args(MatchResult)
        assert set(args) == {"MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"}


# ===================================================================
# Test: Deterministic MATCH_3_WAY resolver
# ===================================================================
class TestMatch3WayResolver:

    def test_po_match_true_yields_match(self):
        state = _state(po_match=True, match_3_way=False)
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "MATCH"
        assert result["match_3_way"] is True

    def test_po_match_false_yields_no_match(self):
        state = _state(po_match=False, match_3_way=True)
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "NO_MATCH"
        assert result["match_3_way"] is False

    def test_po_match_priority_over_match_3_way(self):
        """po_match takes priority over match_3_way."""
        state = _state(po_match=True, match_3_way=False)
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "MATCH"
        entry = json.loads(result["audit_log"][1])
        assert entry["source_flag"] == "po_match"

    def test_fallback_to_match_3_way(self):
        """When po_match is None, fall back to match_3_way."""
        state = _state(po_match=None, match_3_way=True)
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "MATCH"
        entry = json.loads(result["audit_log"][1])
        assert entry["source_flag"] == "match_3_way"

    def test_both_none_yields_unknown(self):
        """When both flags are None, result is UNKNOWN."""
        state = _state(po_match=None, match_3_way=None)
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "UNKNOWN"
        entry = json.loads(result["audit_log"][1])
        assert entry["source_flag"] is None

    def test_missing_both_keys_yields_unknown(self):
        """When keys are absent from state entirely."""
        state = _state()
        del state["po_match"]
        del state["match_3_way"]
        result = execute_node(state, _match3way_node())
        assert result["match_result"] == "UNKNOWN"


# ===================================================================
# Test: source_flag audit log
# ===================================================================
class TestSourceFlagAuditLog:

    def test_audit_log_match_inputs(self):
        state = _state(po_match=True)
        result = execute_node(state, _match3way_node())
        assert len(result["audit_log"]) == 2
        inputs_entry = json.loads(result["audit_log"][0])
        assert inputs_entry["node"] == "MATCH_3_WAY"
        assert inputs_entry["event"] == "match_inputs"
        assert inputs_entry["po_match"] is True

    def test_audit_log_match_result_set(self):
        state = _state(po_match=True)
        result = execute_node(state, _match3way_node())
        assert len(result["audit_log"]) == 2
        entry = json.loads(result["audit_log"][1])
        assert entry["node"] == "MATCH_3_WAY"
        assert entry["event"] == "match_result_set"
        assert entry["match_result"] == "MATCH"
        assert entry["source_flag"] == "po_match"

    def test_audit_log_no_match(self):
        state = _state(po_match=False)
        result = execute_node(state, _match3way_node())
        entry = json.loads(result["audit_log"][1])
        assert entry["match_result"] == "NO_MATCH"

    def test_match_inputs_shows_raw_flags_on_unknown(self):
        """When match_result is UNKNOWN, match_inputs reveals which flags were missing."""
        state = _state(po_match=None, match_3_way=None)
        result = execute_node(state, _match3way_node())
        inputs_entry = json.loads(result["audit_log"][0])
        assert inputs_entry["event"] == "match_inputs"
        assert inputs_entry["po_match"] is None
        assert inputs_entry["match_3_way"] is None

    def test_match_inputs_shows_raw_flags_on_match(self):
        """match_inputs captures the raw input values even on successful match."""
        state = _state(po_match=True, match_3_way=False)
        result = execute_node(state, _match3way_node())
        inputs_entry = json.loads(result["audit_log"][0])
        assert inputs_entry["event"] == "match_inputs"
        assert inputs_entry["po_match"] is True
        assert inputs_entry["match_3_way"] is False


# ===================================================================
# Test: Condition normalization for match_result labels
# ===================================================================
class TestConditionNormalization:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the predicate cache to avoid stale entries from prior tests."""
        _PREDICATE_CACHE.clear()
        yield
        _PREDICATE_CACHE.clear()

    def test_match_3_way_maps_to_match_result(self):
        assert normalize_condition("MATCH_3_WAY") == 'match_result == "MATCH"'

    def test_match_maps_to_match_result(self):
        assert normalize_condition("match") == 'match_result == "MATCH"'

    def test_no_match_maps_to_no_match(self):
        assert normalize_condition("no_match") == 'match_result == "NO_MATCH"'

    def test_variance_maps_to_variance(self):
        assert normalize_condition("variance") == 'match_result == "VARIANCE"'

    def test_variance_above_tolerance_maps(self):
        assert normalize_condition("VARIANCE_ABOVE_TOLERANCE") == 'match_result == "VARIANCE"'

    def test_successful_match_maps(self):
        assert normalize_condition("successful_match") == 'match_result == "MATCH"'

    def test_within_tolerance_maps(self):
        assert normalize_condition("within_tolerance") == 'match_result == "MATCH"'

    def test_above_tolerance_maps(self):
        assert normalize_condition("above_tolerance") == 'match_result == "NO_MATCH"'

    def test_if_condition_remains_none(self):
        assert normalize_condition("IF_CONDITION") is None

    def test_inline_match_result_expression(self):
        """Direct DSL expression passes through normalization."""
        result = normalize_condition('match_result == "MATCH"')
        assert result == 'match_result == "MATCH"'

    def test_predicate_evaluates_match(self):
        pred = get_predicate('match_result == "MATCH"')
        assert pred is not None
        assert pred({"match_result": "MATCH"}) is True
        assert pred({"match_result": "NO_MATCH"}) is False
        assert pred({"match_result": "UNKNOWN"}) is False

    def test_predicate_evaluates_no_match(self):
        pred = get_predicate('match_result == "NO_MATCH"')
        assert pred is not None
        assert pred({"match_result": "NO_MATCH"}) is True
        assert pred({"match_result": "MATCH"}) is False

    def test_predicate_evaluates_unknown(self):
        pred = get_predicate('match_result == "UNKNOWN"')
        assert pred is not None
        assert pred({"match_result": "UNKNOWN"}) is True
        assert pred({"match_result": "MATCH"}) is False


# ===================================================================
# Test: Normalizer guardrail — inject UNKNOWN edge
# ===================================================================
class TestMatchResultUnknownGuardrail:

    def test_injects_unknown_edge(self):
        data = _graph_with_match_result_gw(include_unknown=False)
        data, log = inject_match_result_unknown_guardrail(data)
        unknown_edges = [
            e for e in data["edges"]
            if e.get("condition") == 'match_result == "UNKNOWN"'
        ]
        assert len(unknown_edges) == 1
        assert unknown_edges[0]["frm"] == "n1"
        assert unknown_edges[0]["to"] == "n_exc_unmodeled"

    def test_idempotent(self):
        data = _graph_with_match_result_gw(include_unknown=False)
        inject_match_result_unknown_guardrail(data)
        edge_count_after_first = len(data["edges"])
        inject_match_result_unknown_guardrail(data)
        assert len(data["edges"]) == edge_count_after_first

    def test_already_has_unknown_edge(self):
        data = _graph_with_match_result_gw(include_unknown=True)
        original_edges = len(data["edges"])
        data, log = inject_match_result_unknown_guardrail(data)
        assert len(data["edges"]) == original_edges
        assert any("No match_result gateways" in line for line in log)

    def test_missing_station_raises_valueerror(self):
        data = _graph_with_match_result_gw(
            include_unknown=False, include_station=False
        )
        with pytest.raises(ValueError, match="MANUAL_REVIEW_UNMODELED_GATE"):
            inject_match_result_unknown_guardrail(data)

    def test_no_match_result_edges_is_noop(self):
        """Graph with no match_result references produces no changes."""
        data = {
            "nodes": [
                {"id": "n1", "kind": "gateway", "meta": {}},
                {"id": "n2", "kind": "task", "meta": {}},
            ],
            "edges": [
                {"frm": "n1", "to": "n2", "condition": "has_po == true"},
            ],
        }
        original_edges = len(data["edges"])
        data, log = inject_match_result_unknown_guardrail(data)
        assert len(data["edges"]) == original_edges


# ===================================================================
# Test: match_result only written by MATCH_3_WAY executor
# ===================================================================

class TestMatchResultOnlyFromMatch3Way:
    """Runtime assertion: execute_node for non-MATCH_3_WAY intents
    must NOT include 'match_result' in returned updates."""

    @pytest.mark.parametrize("intent", [
        "ENTER_RECORD",
        "VALIDATE_FIELDS",
        "APPROVE",
        "SCHEDULE_PAYMENT",
        "EXECUTE_PAYMENT",
        "ROUTE_FOR_REVIEW",
    ])
    def test_non_match_intents_do_not_set_match_result(self, intent):
        node = {
            "id": "n_test",
            "kind": "task",
            "name": f"Test {intent}",
            "action": {
                "type": intent,
                "actor_id": "role_system",
                "artifact_id": "art_invoice",
                "extra": {},
            },
            "decision": None,
            "meta": {"canonical_key": f"task:{intent}@n_test",
                     "intent_key": f"task:{intent}"},
        }
        state = _state()
        result = execute_node(state, node)
        assert "match_result" not in result, (
            f"execute_node for {intent} must not write match_result, "
            f"but returned: {result}"
        )

    def test_match3way_does_set_match_result(self):
        """Sanity: MATCH_3_WAY executor writes match_result."""
        state = _state(po_match=True)
        result = execute_node(state, _match3way_node())
        assert "match_result" in result
        assert result["match_result"] == "MATCH"
