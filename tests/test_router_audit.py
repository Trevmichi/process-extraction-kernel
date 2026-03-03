"""
tests/test_router_audit.py
Tests for analyze_routing() — the pure routing analysis function.

Tests cover:
- Short-circuit paths (single_edge, all_same_target)
- 2-phase evaluation (condition_match, unconditional_fallback)
- Exception paths (ambiguous_route, no_route)
- Candidate structure and matched semantics
- Consistency with route_edge()
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.router import RouterError, RouteResult, analyze_routing, route_edge


# ---------------------------------------------------------------------------
# Minimal state helper
# ---------------------------------------------------------------------------

def _state(**overrides) -> dict:
    """Return a minimal APState dict with optional overrides."""
    base = {
        "invoice_id": "TEST",
        "vendor": "Acme",
        "amount": 100.0,
        "has_po": True,
        "po_match": True,
        "match_3_way": True,
        "match_result": "MATCH",
        "status": "NEW",
        "current_node": "",
        "last_gateway": "",
        "audit_log": [],
        "raw_text": "",
        "extraction": {},
        "provenance": {},
    }
    base.update(overrides)
    return base


# ===========================================================================
# Test: single_edge
# ===========================================================================

class TestSingleEdge:

    def test_single_edge(self):
        edges = [{"to": "n5", "condition": None}]
        result = analyze_routing(_state(), edges)
        assert result.selected == "n5"
        assert result.reason == "single_edge"
        assert len(result.candidates) == 1
        assert result.candidates[0]["matched"] is None


# ===========================================================================
# Test: all_same_target
# ===========================================================================

class TestAllSameTarget:

    def test_all_same_target(self):
        edges = [
            {"to": "n5", "condition": "has_po == true"},
            {"to": "n5", "condition": None},
        ]
        result = analyze_routing(_state(), edges)
        assert result.selected == "n5"
        assert result.reason == "all_same_target"
        assert all(c["matched"] is None for c in result.candidates)


# ===========================================================================
# Test: condition_match
# ===========================================================================

class TestConditionMatch:

    def test_condition_match(self):
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n6", "condition": 'match_result == "NO_MATCH"'},
            {"to": "n7", "condition": None},
        ]
        result = analyze_routing(_state(match_result="MATCH"), edges)
        assert result.selected == "n5"
        assert result.reason == "condition_match"
        # Verify matched semantics
        for c in result.candidates:
            if c["condition"] == 'match_result == "MATCH"':
                assert c["matched"] is True
            elif c["condition"] == 'match_result == "NO_MATCH"':
                assert c["matched"] is False
            elif c["condition"] is None:
                assert c["matched"] is None


# ===========================================================================
# Test: unconditional_fallback
# ===========================================================================

class TestUnconditionalFallback:

    def test_unconditional_fallback(self):
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n6", "condition": 'match_result == "NO_MATCH"'},
            {"to": "n7", "condition": None},
        ]
        # State where neither condition matches
        result = analyze_routing(_state(match_result="UNKNOWN"), edges)
        assert result.selected == "n7"
        assert result.reason == "unconditional_fallback"
        # Conditionals are matched=False, unconditional is matched=None
        for c in result.candidates:
            if c["condition"] is not None:
                assert c["matched"] is False
            else:
                assert c["matched"] is None


# ===========================================================================
# Test: ambiguous_route
# ===========================================================================

class TestAmbiguousRoute:

    def test_ambiguous_route(self):
        edges = [
            {"to": "n5", "condition": "has_po == true"},
            {"to": "n6", "condition": "amount > 0"},
        ]
        # Both conditions are true
        result = analyze_routing(_state(has_po=True, amount=100.0), edges)
        assert result.selected is None
        assert result.reason == "ambiguous_route"
        # At least 2 candidates matched
        matched_count = sum(1 for c in result.candidates if c["matched"] is True)
        assert matched_count >= 2


# ===========================================================================
# Test: no_route
# ===========================================================================

class TestNoRoute:

    def test_no_route(self):
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n6", "condition": 'match_result == "NO_MATCH"'},
        ]
        # Neither condition matches, no unconditional fallback
        result = analyze_routing(_state(match_result="UNKNOWN"), edges)
        assert result.selected is None
        assert result.reason == "no_route"
        assert all(c["matched"] is False for c in result.candidates)


# ===========================================================================
# Test: candidates structure
# ===========================================================================

class TestCandidatesStructure:

    def test_candidates_structure(self):
        edges = [
            {"to": "n5", "condition": "has_po == true"},
            {"to": "n6", "condition": None},
        ]
        result = analyze_routing(_state(), edges)
        for c in result.candidates:
            assert "to" in c
            assert "condition" in c
            assert "matched" in c
            assert isinstance(c["to"], str)
            assert c["matched"] is None or isinstance(c["matched"], bool)


# ===========================================================================
# Test: empty edges raises
# ===========================================================================

class TestEmptyEdgesRaises:

    def test_empty_edges_raises(self):
        with pytest.raises(RouterError):
            analyze_routing(_state(), [])


# ===========================================================================
# Test: analyze_routing / route_edge consistency
# ===========================================================================

class TestAnalyzeRouteEdgeConsistency:

    def test_consistency_selected_not_none(self):
        """When analyze_routing selects a target, route_edge returns the same."""
        node_data = {"id": "n_gw", "meta": {}}
        scenarios = [
            # single edge
            ([{"to": "n5", "condition": None}], _state()),
            # condition match
            ([{"to": "n5", "condition": 'match_result == "MATCH"'},
              {"to": "n6", "condition": 'match_result == "NO_MATCH"'}],
             _state(match_result="MATCH")),
            # unconditional fallback
            ([{"to": "n5", "condition": 'match_result == "MATCH"'},
              {"to": "n7", "condition": None}],
             _state(match_result="UNKNOWN")),
        ]
        for edges, state in scenarios:
            result = analyze_routing(state, edges)
            assert result.selected is not None
            actual = route_edge(state, edges, node_data)
            assert result.selected == actual, (
                f"Mismatch for reason={result.reason}: "
                f"analyze={result.selected}, route_edge={actual}"
            )

    def test_consistency_selected_none_raises(self):
        """When analyze_routing returns None, route_edge raises without station_map."""
        node_data = {"id": "n_gw", "meta": {}}
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n6", "condition": 'match_result == "NO_MATCH"'},
        ]
        state = _state(match_result="UNKNOWN")
        result = analyze_routing(state, edges)
        assert result.selected is None
        with pytest.raises(RouterError):
            route_edge(state, edges, node_data)


# ===========================================================================
# Test: matched=None semantics frozen
# ===========================================================================

class TestMatchedNoneSemanticsFrozen:

    def test_short_circuit_all_matched_none(self):
        """single_edge and all_same_target: all candidates have matched=None."""
        # single_edge
        result1 = analyze_routing(_state(), [{"to": "n5", "condition": "has_po == true"}])
        assert result1.reason == "single_edge"
        assert all(c["matched"] is None for c in result1.candidates)

        # all_same_target
        result2 = analyze_routing(_state(), [
            {"to": "n5", "condition": "has_po == true"},
            {"to": "n5", "condition": None},
        ])
        assert result2.reason == "all_same_target"
        assert all(c["matched"] is None for c in result2.candidates)

    def test_unconditional_always_matched_none(self):
        """Unconditional edges are always matched=None, even when selected."""
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n7", "condition": None},
        ]
        # unconditional_fallback: unconditional is selected but matched stays None
        result = analyze_routing(_state(match_result="UNKNOWN"), edges)
        assert result.reason == "unconditional_fallback"
        assert result.selected == "n7"
        for c in result.candidates:
            if c["condition"] is None:
                assert c["matched"] is None

    def test_conditional_matched_true_false(self):
        """Conditional edges get matched=True or matched=False, never None."""
        edges = [
            {"to": "n5", "condition": 'match_result == "MATCH"'},
            {"to": "n6", "condition": 'match_result == "NO_MATCH"'},
            {"to": "n7", "condition": None},
        ]
        result = analyze_routing(_state(match_result="MATCH"), edges)
        for c in result.candidates:
            if c["condition"] is not None:
                assert c["matched"] is True or c["matched"] is False
            else:
                assert c["matched"] is None
