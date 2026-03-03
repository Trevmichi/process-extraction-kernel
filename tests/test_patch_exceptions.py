"""
tests/test_patch_exceptions.py
Unit tests for Phase 2: Fail-Closed Exception Stations.

Covers:
- inject_exception_stations() idempotency
- Correct metadata on all 4 stations (origin, synthetic, patch_id)
- Action schema (type, actor_id, artifact_id, extra.reason)
- ROUTE_FOR_REVIEW executor produces structured audit_log entries
"""
from __future__ import annotations

import copy
import json

import pytest

from patch_logic import EXCEPTION_STATIONS, inject_exception_stations, _EXCEPTION_PATCH_ID
from src.agent.nodes import execute_node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _empty_graph() -> dict:
    """Minimal graph with no nodes/edges."""
    return {"nodes": [], "edges": [], "artifacts": []}


def _graph_with_stations() -> dict:
    """Graph that already contains all 4 exception station nodes."""
    return {"nodes": copy.deepcopy(EXCEPTION_STATIONS), "edges": [], "artifacts": []}


def _mock_state(**overrides) -> dict:
    """Minimal APState for executor tests."""
    base = {
        "invoice_id": "INV-TEST",
        "vendor": "",
        "amount": 0.0,
        "has_po": False,
        "po_match": False,
        "match_3_way": False,
        "status": "NEW",
        "current_node": "",
        "audit_log": [],
        "raw_text": "",
        "extraction": {},
        "provenance": {},
    }
    base.update(overrides)
    return base


# ===================================================================
# Test: inject_exception_stations() — injection
# ===================================================================
class TestInjectExceptionStations:
    """Tests for the inject_exception_stations() function."""

    def test_injects_all_four_stations(self):
        data = _empty_graph()
        changelog = inject_exception_stations(data)

        injected_ids = {n["id"] for n in data["nodes"]}
        assert "n_exc_bad_extraction" in injected_ids
        assert "n_exc_unmodeled_gate" in injected_ids
        assert "n_exc_ambiguous_route" in injected_ids
        assert "n_exc_no_route" in injected_ids
        assert len(data["nodes"]) == 4
        assert any("Injected" in line for line in changelog)

    def test_idempotent_no_duplicates(self):
        data = _empty_graph()
        inject_exception_stations(data)
        assert len(data["nodes"]) == 4

        # Second call should not add duplicates
        changelog = inject_exception_stations(data)
        assert len(data["nodes"]) == 4
        assert any("already present" in line for line in changelog)

    def test_idempotent_partial_presence(self):
        """If 2 of 4 stations already exist, only the missing 2 are injected."""
        data = _empty_graph()
        # Pre-populate 2 stations
        data["nodes"].append(copy.deepcopy(EXCEPTION_STATIONS[0]))  # bad_extraction
        data["nodes"].append(copy.deepcopy(EXCEPTION_STATIONS[1]))  # unmodeled_gate

        changelog = inject_exception_stations(data)
        assert len(data["nodes"]) == 4
        ids = {n["id"] for n in data["nodes"]}
        assert ids == {"n_exc_bad_extraction", "n_exc_unmodeled_gate",
                       "n_exc_ambiguous_route", "n_exc_no_route"}
        assert any("Injected" in line for line in changelog)

    def test_does_not_touch_existing_nodes(self):
        """Pre-existing nodes in the graph are not modified."""
        data = _empty_graph()
        existing_node = {"id": "n99", "kind": "task", "name": "Existing"}
        data["nodes"].append(existing_node)

        inject_exception_stations(data)
        assert len(data["nodes"]) == 5
        assert data["nodes"][0] == existing_node


# ===================================================================
# Test: Metadata on exception stations
# ===================================================================
class TestExceptionStationMetadata:
    """Validate metadata fields on all 4 exception station definitions."""

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_origin_is_patch(self, station):
        assert station["meta"]["origin"] == "patch"

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_synthetic_is_true(self, station):
        assert station["meta"]["synthetic"] is True

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_patch_id(self, station):
        assert station["meta"]["patch_id"] == _EXCEPTION_PATCH_ID

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_canonical_key_prefix(self, station):
        assert station["meta"]["canonical_key"].startswith("task:MANUAL_REVIEW_")

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_kind_is_task(self, station):
        assert station["kind"] == "task"

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_has_rationale(self, station):
        assert station["meta"].get("rationale")


# ===================================================================
# Test: Action schema on exception stations
# ===================================================================
class TestExceptionStationActionSchema:
    """Validate the action dict structure on all 4 stations."""

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_action_type_is_route_for_review(self, station):
        assert station["action"]["type"] == "ROUTE_FOR_REVIEW"

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_action_has_actor_id(self, station):
        assert station["action"]["actor_id"]

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_action_has_artifact_id(self, station):
        assert station["action"]["artifact_id"]

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_action_extra_has_reason(self, station):
        assert "reason" in station["action"]["extra"]
        assert isinstance(station["action"]["extra"]["reason"], str)
        assert station["action"]["extra"]["reason"]  # non-empty

    def test_reason_codes_are_unique(self):
        reasons = [s["action"]["extra"]["reason"] for s in EXCEPTION_STATIONS]
        assert len(reasons) == len(set(reasons))

    def test_expected_reason_codes(self):
        reasons = {s["action"]["extra"]["reason"] for s in EXCEPTION_STATIONS}
        assert reasons == {
            "BAD_EXTRACTION",
            "UNMODELED_GATE",
            "AMBIGUOUS_ROUTE",
            "NO_ROUTE",
        }


# ===================================================================
# Test: ROUTE_FOR_REVIEW executor in nodes.py
# ===================================================================
class TestRouteForReviewExecutor:
    """Test that execute_node handles ROUTE_FOR_REVIEW correctly."""

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_produces_structured_audit_log(self, station):
        state = _mock_state()
        result = execute_node(state, station)

        assert len(result["audit_log"]) == 1
        entry = json.loads(result["audit_log"][0])
        assert entry["event"] == "exception_station"
        assert entry["reason"] == station["action"]["extra"]["reason"]
        assert entry["node"] == station["meta"]["canonical_key"]

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_sets_exception_status(self, station):
        state = _mock_state()
        result = execute_node(state, station)
        reason = station["action"]["extra"]["reason"]
        assert result["status"] == f"EXCEPTION_{reason}"

    @pytest.mark.parametrize("station", EXCEPTION_STATIONS,
                             ids=[s["id"] for s in EXCEPTION_STATIONS])
    def test_sets_current_node(self, station):
        state = _mock_state()
        result = execute_node(state, station)
        assert result["current_node"] == station["id"]

    def test_bad_extraction_status(self):
        station = EXCEPTION_STATIONS[0]  # BAD_EXTRACTION
        state = _mock_state()
        result = execute_node(state, station)
        assert result["status"] == "EXCEPTION_BAD_EXTRACTION"

    def test_unmodeled_gate_status(self):
        station = EXCEPTION_STATIONS[1]  # UNMODELED_GATE
        state = _mock_state()
        result = execute_node(state, station)
        assert result["status"] == "EXCEPTION_UNMODELED_GATE"

    def test_ambiguous_route_status(self):
        station = EXCEPTION_STATIONS[2]  # AMBIGUOUS_ROUTE
        state = _mock_state()
        result = execute_node(state, station)
        assert result["status"] == "EXCEPTION_AMBIGUOUS_ROUTE"

    def test_no_route_status(self):
        station = EXCEPTION_STATIONS[3]  # NO_ROUTE
        state = _mock_state()
        result = execute_node(state, station)
        assert result["status"] == "EXCEPTION_NO_ROUTE"

    def test_unknown_reason_fallback(self):
        """A ROUTE_FOR_REVIEW node with no extra.reason defaults to UNKNOWN."""
        node_data = {
            "id": "n_test",
            "kind": "task",
            "action": {"type": "ROUTE_FOR_REVIEW", "extra": {}},
            "decision": None,
            "meta": {"canonical_key": "task:TEST"},
        }
        state = _mock_state()
        result = execute_node(state, node_data)
        assert result["status"] == "EXCEPTION_UNKNOWN"
        entry = json.loads(result["audit_log"][0])
        assert entry["reason"] == "UNKNOWN"

    def test_missing_extra_key(self):
        """A ROUTE_FOR_REVIEW node with no extra at all still works."""
        node_data = {
            "id": "n_test2",
            "kind": "task",
            "action": {"type": "ROUTE_FOR_REVIEW"},
            "decision": None,
            "meta": {"canonical_key": "task:TEST2"},
        }
        state = _mock_state()
        result = execute_node(state, node_data)
        assert result["status"] == "EXCEPTION_UNKNOWN"
