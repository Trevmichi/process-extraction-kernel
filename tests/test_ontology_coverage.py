"""
tests/test_ontology_coverage.py
Semantic coverage tests for the ontology vocabulary.

Verifies that the runtime ontology sets (VALID_ACTIONS, VALID_DECISIONS,
VALID_STATUSES, KNOWN_STRUCTURED_GATEWAY_TYPES) remain consistent with
the actual values used in production artifacts: patched graph JSON,
gold evaluation dataset, and injected patch nodes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ontology import (
    EXCEPTION_STATUSES,
    KNOWN_STRUCTURED_GATEWAY_TYPES,
    TERMINAL_STATUSES,
    VALID_ACTIONS,
    VALID_DECISIONS,
    VALID_STATUSES,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PATCHED_PATH = Path(__file__).parent.parent / "outputs" / "ap_master_manual_auto_patched.json"
EXPECTED_PATH = Path(__file__).parent.parent / "datasets" / "expected.jsonl"


@pytest.fixture(scope="module")
def patched_graph() -> dict:
    if not PATCHED_PATH.exists():
        pytest.skip("Patched graph not found")
    return json.loads(PATCHED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold_records() -> list[dict]:
    if not EXPECTED_PATH.exists():
        pytest.skip("Gold dataset not found")
    records = []
    for line in EXPECTED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Patched graph: action types
# ---------------------------------------------------------------------------

class TestGraphActionCoverage:
    """All action types in the patched graph must be in VALID_ACTIONS."""

    def test_all_task_action_types_in_ontology(self, patched_graph: dict) -> None:
        graph_actions: set[str] = set()
        for node in patched_graph["nodes"]:
            action = node.get("action") or {}
            atype = action.get("type")
            if atype:
                graph_actions.add(atype)

        unknown = graph_actions - VALID_ACTIONS
        assert not unknown, (
            f"Graph contains action types not in VALID_ACTIONS: {sorted(unknown)}"
        )

    def test_ontology_covers_patch_injected_actions(self) -> None:
        from patch_logic import EXCEPTION_STATIONS, NEW_NODES

        for node in NEW_NODES + EXCEPTION_STATIONS:
            action = node.get("action") or {}
            atype = action.get("type")
            if atype:
                assert atype in VALID_ACTIONS, (
                    f"Injected node {node['id']!r} has action type {atype!r} "
                    f"not in VALID_ACTIONS"
                )


# ---------------------------------------------------------------------------
# Patched graph: decision types
# ---------------------------------------------------------------------------

class TestGraphDecisionCoverage:
    """All decision types in the patched graph must be in VALID_DECISIONS."""

    def test_all_gateway_decision_types_in_ontology(self, patched_graph: dict) -> None:
        graph_decisions: set[str] = set()
        for node in patched_graph["nodes"]:
            decision = node.get("decision") or {}
            dtype = decision.get("type")
            if dtype:
                graph_decisions.add(dtype)

        unknown = graph_decisions - VALID_DECISIONS
        assert not unknown, (
            f"Graph contains decision types not in VALID_DECISIONS: {sorted(unknown)}"
        )

    def test_ontology_covers_patch_injected_decisions(self) -> None:
        from patch_logic import EXCEPTION_STATIONS, NEW_NODES

        for node in NEW_NODES + EXCEPTION_STATIONS:
            decision = node.get("decision") or {}
            dtype = decision.get("type")
            if dtype:
                assert dtype in VALID_DECISIONS, (
                    f"Injected node {node['id']!r} has decision type {dtype!r} "
                    f"not in VALID_DECISIONS"
                )


# ---------------------------------------------------------------------------
# Gold dataset: expected statuses
# ---------------------------------------------------------------------------

class TestGoldDatasetStatusCoverage:
    """All expected statuses in the gold dataset must be in VALID_STATUSES."""

    def test_all_expected_statuses_in_ontology(self, gold_records: list[dict]) -> None:
        gold_statuses: set[str] = set()
        for rec in gold_records:
            gold_statuses.update(rec["expected_status"])

        unknown = gold_statuses - VALID_STATUSES
        assert not unknown, (
            f"Gold dataset uses statuses not in VALID_STATUSES: {sorted(unknown)}"
        )


# ---------------------------------------------------------------------------
# Gateway type set: consistency with normalize_graph.py
# ---------------------------------------------------------------------------

class TestGatewayTypeConsistency:
    """KNOWN_STRUCTURED_GATEWAY_TYPES must match normalize_graph.py's usage."""

    def test_normalize_graph_imports_from_ontology(self) -> None:
        """normalize_graph.py should use the ontology set, not a private copy."""
        import src.normalize_graph as ng
        # The module should alias from ontology — verify it's the same object
        assert ng._KNOWN_STRUCTURED_GATEWAY_TYPES is KNOWN_STRUCTURED_GATEWAY_TYPES

    def test_gateway_types_are_subset_of_decisions(self) -> None:
        """All structured gateway types should be valid decision types."""
        unknown = KNOWN_STRUCTURED_GATEWAY_TYPES - VALID_DECISIONS
        assert not unknown, (
            f"KNOWN_STRUCTURED_GATEWAY_TYPES contains types not in "
            f"VALID_DECISIONS: {sorted(unknown)}"
        )


# ---------------------------------------------------------------------------
# Status set consistency
# ---------------------------------------------------------------------------

class TestStatusSetConsistency:
    """Verify relationships between status sets."""

    def test_terminal_statuses_are_valid(self) -> None:
        unknown = TERMINAL_STATUSES - VALID_STATUSES
        assert not unknown, f"TERMINAL_STATUSES has invalid entries: {sorted(unknown)}"

    def test_exception_statuses_are_terminal(self) -> None:
        non_terminal = EXCEPTION_STATUSES - TERMINAL_STATUSES
        assert not non_terminal, (
            f"EXCEPTION_STATUSES has non-terminal entries: {sorted(non_terminal)}"
        )

    def test_exception_statuses_all_prefixed(self) -> None:
        for s in EXCEPTION_STATUSES:
            assert s.startswith("EXCEPTION_"), (
                f"Exception status {s!r} missing EXCEPTION_ prefix"
            )

    def test_transitional_statuses_not_terminal(self) -> None:
        transitional = {"NEW", "DATA_EXTRACTED", "NEEDS_RETRY", "VALIDATED", "PENDING_INFO"}
        overlap = transitional & TERMINAL_STATUSES
        assert not overlap, (
            f"Transitional statuses should not be terminal: {sorted(overlap)}"
        )
