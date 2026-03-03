"""
tests/test_linter.py
Unit tests for the graph linter (src/linter.py).

All tests operate on plain Python dicts (no file I/O needed), except for
tests that explicitly load the JSON fixtures to prove reproducibility.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.linter import LintError, lint_process_graph, assert_graph_valid

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def error_codes(graph: dict) -> list[str]:
    """Return list of error-severity codes from lint_process_graph."""
    return [e.code for e in lint_process_graph(graph) if e.severity == "error"]


def warning_codes(graph: dict) -> list[str]:
    return [e.code for e in lint_process_graph(graph) if e.severity == "warning"]


# ---------------------------------------------------------------------------
# Minimal valid graph helper (in-memory, avoids file dependency)
# ---------------------------------------------------------------------------

def _minimal_valid() -> dict:
    """Return a small but fully-valid process graph dict."""
    return {
        "actors":    [{"id": "role_clerk", "type": "human_role", "name": "Clerk"}],
        "artifacts": [{"id": "art_invoice", "type": "document", "name": "Invoice"}],
        "nodes": [
            {
                "id": "n1", "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            {
                "id": "n2", "kind": "task", "name": "Enter Record",
                "action": {
                    "type": "ENTER_RECORD",
                    "actor_id": "role_clerk",
                    "artifact_id": "art_invoice",
                    "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:ENTER_RECORD"},
            },
            {
                "id": "n3", "kind": "end", "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
        ],
        "edges": [
            {"frm": "n1", "to": "n2", "condition": None},
            {"frm": "n2", "to": "n3", "condition": None},
        ],
    }


def _minimal_with_gateway() -> dict:
    """Return a valid graph that includes a two-branch gateway."""
    base = _minimal_valid()
    # Replace linear n2→n3 with n2→gw→n3/n4→n5
    base["nodes"] = [
        {
            "id": "n1", "kind": "event", "name": "Start",
            "action": None, "decision": None, "evidence": [],
            "meta": {"canonical_key": "event:start"},
        },
        {
            "id": "n2", "kind": "task", "name": "Enter Record",
            "action": {
                "type": "ENTER_RECORD",
                "actor_id": "role_clerk",
                "artifact_id": "art_invoice",
                "extra": {},
            },
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:ENTER_RECORD"},
        },
        {
            "id": "gw1", "kind": "gateway", "name": "Has PO?",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO"},
        },
        {
            "id": "n3", "kind": "task", "name": "Approve",
            "action": {
                "type": "APPROVE",
                "actor_id": "role_clerk",
                "artifact_id": "art_invoice",
                "extra": {},
            },
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:APPROVE"},
        },
        {
            "id": "n4", "kind": "task", "name": "Reject",
            "action": {
                "type": "REJECT",
                "actor_id": "role_clerk",
                "artifact_id": "art_invoice",
                "extra": {},
            },
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:REJECT"},
        },
        {
            "id": "n5", "kind": "end", "name": "End",
            "action": None, "decision": None, "evidence": [],
            "meta": {"canonical_key": "end:end"},
        },
    ]
    base["edges"] = [
        {"frm": "n1",  "to": "n2",  "condition": None},
        {"frm": "n2",  "to": "gw1", "condition": None},
        {"frm": "gw1", "to": "n3",  "condition": "has_po == true"},
        {"frm": "gw1", "to": "n4",  "condition": "has_po == false"},
        {"frm": "n3",  "to": "n5",  "condition": None},
        {"frm": "n4",  "to": "n5",  "condition": None},
    ]
    return base


# ===========================================================================
# (A) Happy path — graph_minimal_ok.json
# ===========================================================================

class TestMinimalOkFixture:
    """The fixture graph_minimal_ok.json must produce zero errors."""

    def test_no_errors(self):
        graph = load_fixture("graph_minimal_ok.json")
        errs = [e for e in lint_process_graph(graph) if e.severity == "error"]
        assert errs == [], f"Expected no errors, got:\n" + "\n".join(str(e) for e in errs)

    def test_assert_graph_valid_does_not_raise(self):
        graph = load_fixture("graph_minimal_ok.json")
        assert_graph_valid(graph)   # must not raise

    def test_in_memory_minimal_valid_no_errors(self):
        graph = _minimal_valid()
        errs = error_codes(graph)
        assert errs == []

    def test_in_memory_gateway_valid_no_errors(self):
        graph = _minimal_with_gateway()
        errs = error_codes(graph)
        assert errs == []


# ===========================================================================
# (A) Node / edge referential integrity
# ===========================================================================

class TestNodeEdgeIntegrity:

    def test_duplicate_node_id(self):
        graph = _minimal_valid()
        # Add a second node with the same id as n2
        graph["nodes"].append({
            "id": "n2", "kind": "task", "name": "Duplicate",
            "action": {
                "type": "ENTER_RECORD",
                "actor_id": "role_clerk",
                "artifact_id": "art_invoice",
                "extra": {},
            },
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:DUPLICATE_KEY"},
        })
        assert "E_NODE_ID_DUP" in error_codes(graph)

    def test_edge_ref_unknown_frm(self):
        graph = _minimal_valid()
        graph["edges"].append({"frm": "n_ghost", "to": "n3", "condition": None})
        assert "E_EDGE_REF" in error_codes(graph)

    def test_edge_ref_unknown_to(self):
        graph = _minimal_valid()
        graph["edges"].append({"frm": "n1", "to": "n_ghost", "condition": None})
        assert "E_EDGE_REF" in error_codes(graph)

    def test_canonical_key_missing(self):
        graph = _minimal_valid()
        # Remove canonical_key from n2
        del graph["nodes"][1]["meta"]["canonical_key"]
        assert "E_CANONICAL_KEY_MISSING" in error_codes(graph)

    def test_canonical_key_duplicate(self):
        graph = _minimal_valid()
        # Make n3 share canonical_key with n2
        graph["nodes"][2]["meta"]["canonical_key"] = "task:ENTER_RECORD"
        graph["nodes"][2]["kind"] = "task"
        assert "E_CANONICAL_KEY_DUP" in error_codes(graph)

    def test_duplicate_frm_to_edge(self):
        graph = _minimal_valid()
        # Add the same n1→n2 edge again
        graph["edges"].append({"frm": "n1", "to": "n2", "condition": None})
        assert "E_EDGE_DUP" in error_codes(graph)


# ===========================================================================
# (B) Actor / artifact integrity
# ===========================================================================

class TestActorArtifactIntegrity:

    def test_missing_artifact_id_reference(self):
        """Node action.artifact_id points to non-existent artifact."""
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["artifact_id"] = "art_account_code"
        assert "E_ARTIFACT_MISSING" in error_codes(graph)

    def test_empty_artifact_id_is_error(self):
        """Empty string artifact_id counts as missing."""
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["artifact_id"] = ""
        assert "E_ARTIFACT_MISSING" in error_codes(graph)

    def test_missing_actor_id_reference(self):
        """Node action.actor_id points to non-existent actor."""
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["actor_id"] = "role_cfo"
        assert "E_ACTOR_MISSING" in error_codes(graph)

    def test_empty_actor_id_is_error(self):
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["actor_id"] = ""
        assert "E_ACTOR_MISSING" in error_codes(graph)


# ===========================================================================
# (C) Gateway semantics
# ===========================================================================

class TestGatewaySemantics:

    def test_gateway_fanout_same_condition_from_fixture(self):
        """graph_bad_haspo_fanout.json must trigger E_GATEWAY_FANOUT_SAME_CONDITION."""
        graph = load_fixture("graph_bad_haspo_fanout.json")
        assert "E_GATEWAY_FANOUT_SAME_CONDITION" in error_codes(graph)

    def test_gateway_fanout_identical_conditions_in_memory(self):
        """Two gateway edges with the same condition trigger the error."""
        graph = _minimal_with_gateway()
        # Replace the two different conditions with identical ones
        for e in graph["edges"]:
            if e["frm"] == "gw1":
                e["condition"] = "has_po == true"   # both now identical
        assert "E_GATEWAY_FANOUT_SAME_CONDITION" in error_codes(graph)

    def test_gateway_fanout_same_after_normalization(self):
        """'HAS_PO' and 'has_po == true' normalize to the same string → error."""
        graph = _minimal_with_gateway()
        edges = [e for e in graph["edges"] if e["frm"] == "gw1"]
        edges[0]["condition"] = "HAS_PO"           # normalizes to has_po == true
        edges[1]["condition"] = "has_po == true"   # already canonical
        assert "E_GATEWAY_FANOUT_SAME_CONDITION" in error_codes(graph)

    def test_gateway_too_few_edges(self):
        """A gateway with only 1 outgoing edge triggers E_GATEWAY_TOO_FEW_EDGES."""
        graph = _minimal_with_gateway()
        # Remove one of the gateway's outgoing edges
        graph["edges"] = [
            e for e in graph["edges"]
            if not (e["frm"] == "gw1" and e["to"] == "n4")
        ]
        assert "E_GATEWAY_TOO_FEW_EDGES" in error_codes(graph)

    def test_gateway_null_condition_is_error(self):
        """Gateway edges with null conditions are invalid."""
        graph = _minimal_with_gateway()
        for e in graph["edges"]:
            if e["frm"] == "gw1":
                e["condition"] = None   # both null
        assert "E_GATEWAY_NULL_CONDITION" in error_codes(graph)

    def test_gateway_unparseable_condition(self):
        """Non-normalizable condition labels on gateway edge → E_CONDITION_PARSE."""
        graph = _minimal_with_gateway()
        for e in graph["edges"]:
            if e["frm"] == "gw1" and e["to"] == "n3":
                e["condition"] = "IF_CONDITION"   # cannot normalize
        assert "E_CONDITION_PARSE" in error_codes(graph)

    def test_gateway_wide_fanout_warning(self):
        """Gateway with 4 outgoing edges emits W_GATEWAY_WIDE_FANOUT warning."""
        graph = _minimal_with_gateway()
        # Add two more outgoing edges (need extra target nodes too)
        graph["actors"].append({"id": "role_dir", "type": "human_role", "name": "Dir"})
        for tag in ("n_extra_a", "n_extra_b"):
            graph["nodes"].append({
                "id": tag, "kind": "task", "name": tag,
                "action": {
                    "type": "APPROVE",
                    "actor_id": "role_dir",
                    "artifact_id": "art_invoice",
                    "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:APPROVE_{tag}"},
            })
        # Use distinct but valid-looking conditions (different amount thresholds)
        conditions = ["has_po == true", "has_po == false",
                      "amount > 10000", "amount <= 10000"]
        for i, (e, cond) in enumerate(zip(
            [e for e in graph["edges"] if e["frm"] == "gw1"],
            conditions[:2],
        )):
            e["condition"] = cond

        graph["edges"].append({"frm": "gw1", "to": "n_extra_a", "condition": "amount > 10000"})
        graph["edges"].append({"frm": "gw1", "to": "n_extra_b", "condition": "amount <= 10000"})

        # n_extra_a and n_extra_b need end edges
        n5_id = [n["id"] for n in graph["nodes"] if n["kind"] == "end"][0]
        graph["edges"].append({"frm": "n_extra_a", "to": n5_id, "condition": None})
        graph["edges"].append({"frm": "n_extra_b", "to": n5_id, "condition": None})

        warns = warning_codes(graph)
        assert "W_GATEWAY_WIDE_FANOUT" in warns

    def test_valid_two_branch_gateway_no_gateway_errors(self):
        """A well-formed two-branch gateway produces no gateway errors."""
        graph = _minimal_with_gateway()
        gw_errors = [
            c for c in error_codes(graph)
            if c.startswith("E_GATEWAY") or c == "E_CONDITION_PARSE"
        ]
        assert gw_errors == []


# ===========================================================================
# (D) Semantic consistency warnings
# ===========================================================================

class TestSemanticConsistency:

    def test_gateway_with_action_emits_warning(self):
        graph = _minimal_with_gateway()
        # Give the gateway an action (semantically wrong)
        for n in graph["nodes"]:
            if n["id"] == "gw1":
                n["action"] = {"type": "DO_THING", "actor_id": "role_clerk",
                                "artifact_id": "art_invoice", "extra": {}}
        warns = warning_codes(graph)
        assert "W_SEMANTIC_CONFLATION" in warns

    def test_task_with_decision_emits_warning(self):
        graph = _minimal_valid()
        graph["nodes"][1]["decision"] = {"type": "SOME_DECISION", "inputs": []}
        warns = warning_codes(graph)
        assert "W_SEMANTIC_CONFLATION" in warns


# ===========================================================================
# assert_graph_valid raises ValueError with report
# ===========================================================================

class TestAssertGraphValid:

    def test_raises_on_errors(self):
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["artifact_id"] = "art_missing"
        with pytest.raises(ValueError) as exc_info:
            assert_graph_valid(graph)
        msg = str(exc_info.value)
        assert "E_ARTIFACT_MISSING" in msg
        assert "Graph validation failed" in msg

    def test_report_lists_all_errors(self):
        """Multiple errors all appear in the raised message."""
        graph = _minimal_valid()
        # Introduce two distinct errors
        graph["nodes"][1]["action"]["artifact_id"] = "art_missing"
        graph["edges"].append({"frm": "n1", "to": "n2", "condition": None})  # dup edge
        with pytest.raises(ValueError) as exc_info:
            assert_graph_valid(graph)
        msg = str(exc_info.value)
        assert "E_ARTIFACT_MISSING" in msg
        assert "E_EDGE_DUP" in msg

    def test_does_not_raise_on_warnings_only(self):
        """Warnings alone must not cause assert_graph_valid to raise."""
        graph = _minimal_valid()
        # Add a decision to a task node (warning, not error)
        graph["nodes"][1]["decision"] = {"type": "SOME_DECISION", "inputs": []}
        # This only produces W_SEMANTIC_CONFLATION — no errors → must not raise
        assert_graph_valid(graph)


# ===========================================================================
# (E) Structural invariants — match split pattern
# ===========================================================================

def _graph_with_valid_match_split() -> dict:
    """Return a graph with a correctly-split MATCH_3_WAY task + decision gateway."""
    return {
        "actors":    [{"id": "role_clerk", "type": "human_role", "name": "Clerk"}],
        "artifacts": [{"id": "art_invoice", "type": "document", "name": "Invoice"}],
        "nodes": [
            {
                "id": "n1", "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            # n5: task (split from gateway)
            {
                "id": "n5", "kind": "task", "name": "3-Way Match",
                "action": {"type": "MATCH_3_WAY", "actor_id": "role_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY@n5",
                         "intent_key": "gw:MATCH_3_WAY"},
            },
            # n5_decision: gateway (injected by split)
            {
                "id": "n5_decision", "kind": "gateway",
                "name": "Match Decision (n5)",
                "action": None,
                "decision": {"type": "MATCH_DECISION", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_DECISION@n5_decision",
                         "intent_key": "gw:MATCH_DECISION"},
            },
            # Branch targets
            {
                "id": "n_approve", "kind": "task", "name": "Approve",
                "action": {"type": "APPROVE", "actor_id": "role_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE@n_approve"},
            },
            {
                "id": "n_no_match", "kind": "task", "name": "No Match Review",
                "action": {"type": "MANUAL_REVIEW_MATCH_FAILED",
                           "actor_id": "role_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_MATCH_FAILED@n_no_match"},
            },
            {
                "id": "n_unknown", "kind": "task", "name": "Unknown Review",
                "action": {"type": "MANUAL_REVIEW_UNMODELED_GATE",
                           "actor_id": "role_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_unknown"},
            },
            {
                "id": "n_end", "kind": "end", "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
        ],
        "edges": [
            {"frm": "n1", "to": "n5", "condition": None},
            # task → decision (unconditional)
            {"frm": "n5", "to": "n5_decision", "condition": None},
            # decision → 3 branches
            {"frm": "n5_decision", "to": "n_approve",  "condition": 'match_result == "MATCH"'},
            {"frm": "n5_decision", "to": "n_no_match", "condition": 'match_result == "NO_MATCH"'},
            {"frm": "n5_decision", "to": "n_unknown",  "condition": 'match_result == "UNKNOWN"'},
            # targets → end
            {"frm": "n_approve",  "to": "n_end", "condition": None},
            {"frm": "n_no_match", "to": "n_end", "condition": None},
            {"frm": "n_unknown",  "to": "n_end", "condition": None},
        ],
    }


class TestMatchSplitInvariants:
    """Tests for E_MATCH_SPLIT_* lint codes."""

    def test_valid_split_no_errors(self):
        """Correctly-split match pattern produces no match-split errors."""
        graph = _graph_with_valid_match_split()
        codes = error_codes(graph)
        split_errors = [c for c in codes if c.startswith("E_MATCH_SPLIT")]
        assert split_errors == []

    def test_missing_decision_node(self):
        """Removing n5_decision triggers E_MATCH_SPLIT_MISSING_DECISION."""
        graph = _graph_with_valid_match_split()
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "n5_decision"]
        graph["edges"] = [e for e in graph["edges"]
                          if e.get("frm") != "n5_decision"
                          and e.get("to") != "n5_decision"]
        # Need to give n5 an outgoing edge so it doesn't also trigger other errors
        graph["edges"].append({"frm": "n5", "to": "n_end", "condition": None})
        assert "E_MATCH_SPLIT_MISSING_DECISION" in error_codes(graph)

    def test_decision_wrong_kind(self):
        """Decision node with kind='task' triggers E_MATCH_SPLIT_MISSING_DECISION."""
        graph = _graph_with_valid_match_split()
        for n in graph["nodes"]:
            if n["id"] == "n5_decision":
                n["kind"] = "task"
                n["action"] = {"type": "MATCH_DECISION", "actor_id": "role_clerk",
                               "artifact_id": "art_invoice", "extra": {}}
        assert "E_MATCH_SPLIT_MISSING_DECISION" in error_codes(graph)

    def test_decision_wrong_type(self):
        """Decision node with wrong decision.type triggers E_MATCH_SPLIT_MISSING_DECISION."""
        graph = _graph_with_valid_match_split()
        for n in graph["nodes"]:
            if n["id"] == "n5_decision":
                n["decision"]["type"] = "WRONG_TYPE"
        assert "E_MATCH_SPLIT_MISSING_DECISION" in error_codes(graph)

    def test_task_not_converted(self):
        """n5 still a gateway triggers E_MATCH_SPLIT_BAD_TASK_TO_GATE."""
        graph = _graph_with_valid_match_split()
        for n in graph["nodes"]:
            if n["id"] == "n5":
                n["kind"] = "gateway"
                n["action"] = None
                n["decision"] = {"type": "MATCH_3_WAY", "inputs": []}
        assert "E_MATCH_SPLIT_BAD_TASK_TO_GATE" in error_codes(graph)

    def test_task_wrong_action_type(self):
        """n5 with wrong action.type triggers E_MATCH_SPLIT_BAD_TASK_TO_GATE."""
        graph = _graph_with_valid_match_split()
        for n in graph["nodes"]:
            if n["id"] == "n5":
                n["action"]["type"] = "ENTER_RECORD"
        assert "E_MATCH_SPLIT_BAD_TASK_TO_GATE" in error_codes(graph)

    def test_task_extra_outgoing_edge(self):
        """n5 with extra outgoing edge triggers E_MATCH_SPLIT_BAD_TASK_TO_GATE."""
        graph = _graph_with_valid_match_split()
        graph["edges"].append({"frm": "n5", "to": "n_end", "condition": None})
        assert "E_MATCH_SPLIT_BAD_TASK_TO_GATE" in error_codes(graph)

    def test_non_exhaustive_missing_unknown(self):
        """Decision gateway missing UNKNOWN branch → E_MATCH_SPLIT_NON_EXHAUSTIVE."""
        graph = _graph_with_valid_match_split()
        graph["edges"] = [
            e for e in graph["edges"]
            if not (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "UNKNOWN"')
        ]
        assert "E_MATCH_SPLIT_NON_EXHAUSTIVE" in error_codes(graph)

    def test_non_exhaustive_extra_condition(self):
        """Decision gateway with extra branch → E_MATCH_SPLIT_NON_EXHAUSTIVE."""
        graph = _graph_with_valid_match_split()
        graph["edges"].append({
            "frm": "n5_decision", "to": "n_end",
            "condition": 'match_result == "PARTIAL"',
        })
        assert "E_MATCH_SPLIT_NON_EXHAUSTIVE" in error_codes(graph)

    def test_bypass_inbound_edge(self):
        """Edge from n1 → n5_decision (bypass) → E_MATCH_SPLIT_BYPASS_INBOUND."""
        graph = _graph_with_valid_match_split()
        graph["edges"].append({"frm": "n1", "to": "n5_decision", "condition": None})
        assert "E_MATCH_SPLIT_BYPASS_INBOUND" in error_codes(graph)

    def test_skips_n4(self):
        """Nodes with id='n4' are skipped (handled by pass 5, not the split)."""
        graph = _graph_with_valid_match_split()
        # Add a node n4 with gw:MATCH_3_WAY in meta but no _decision node
        graph["nodes"].append({
            "id": "n4", "kind": "gateway", "name": "Primary Match",
            "action": None,
            "decision": {"type": "MATCH_3_WAY", "inputs": []},
            "evidence": [],
            "meta": {"canonical_key": "gw:MATCH_3_WAY@n4",
                     "intent_key": "gw:MATCH_3_WAY"},
        })
        graph["edges"].append(
            {"frm": "n4", "to": "n_approve", "condition": 'match_result == "MATCH"'})
        graph["edges"].append(
            {"frm": "n4", "to": "n_no_match", "condition": 'match_result == "NO_MATCH"'})
        # No n4_decision node — but n4 should be skipped
        codes = error_codes(graph)
        split_errors = [c for c in codes if c.startswith("E_MATCH_SPLIT")]
        assert split_errors == []


# ===========================================================================
# (E) Structural invariants — placeholder conditions
# ===========================================================================

class TestPlaceholderCondition:
    """Tests for E_PLACEHOLDER_CONDITION lint code."""

    def test_if_condition_on_edge(self):
        """Edge with IF_CONDITION triggers E_PLACEHOLDER_CONDITION."""
        graph = _minimal_with_gateway()
        for e in graph["edges"]:
            if e["frm"] == "gw1" and e["to"] == "n3":
                e["condition"] = "IF_CONDITION"
        assert "E_PLACEHOLDER_CONDITION" in error_codes(graph)

    def test_schedule_payment_as_condition(self):
        """SCHEDULE_PAYMENT used as condition triggers E_PLACEHOLDER_CONDITION."""
        graph = _minimal_with_gateway()
        for e in graph["edges"]:
            if e["frm"] == "gw1" and e["to"] == "n3":
                e["condition"] = "SCHEDULE_PAYMENT"
        assert "E_PLACEHOLDER_CONDITION" in error_codes(graph)

    def test_approve_as_condition(self):
        """APPROVE used as condition triggers E_PLACEHOLDER_CONDITION."""
        graph = _minimal_with_gateway()
        for e in graph["edges"]:
            if e["frm"] == "gw1" and e["to"] == "n3":
                e["condition"] = "APPROVE"
        assert "E_PLACEHOLDER_CONDITION" in error_codes(graph)

    def test_valid_conditions_no_placeholder_errors(self):
        """Well-formed conditions produce no placeholder errors."""
        graph = _minimal_with_gateway()
        codes = error_codes(graph)
        assert "E_PLACEHOLDER_CONDITION" not in codes

    def test_placeholder_on_non_gateway_edge(self):
        """Placeholder on a task→task edge is also caught."""
        graph = _minimal_valid()
        # Add a condition to a non-gateway edge
        graph["edges"][0]["condition"] = "IF_CONDITION"
        assert "E_PLACEHOLDER_CONDITION" in error_codes(graph)


# ===========================================================================
# (E) Structural invariants — match_result ownership
# ===========================================================================

class TestMatchResultOwnership:
    """Tests for E_MATCH_RESULT_FOREIGN_WRITER lint code."""

    def test_match3way_node_allowed(self):
        """MATCH_3_WAY node with match_result in extra is fine."""
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["type"] = "MATCH_3_WAY"
        graph["nodes"][1]["action"]["extra"] = {"match_result": "MATCH"}
        assert "E_MATCH_RESULT_FOREIGN_WRITER" not in error_codes(graph)

    def test_other_node_with_match_result_in_extra(self):
        """Non-MATCH_3_WAY node with match_result in extra → error."""
        graph = _minimal_valid()
        graph["nodes"][1]["action"]["extra"] = {"match_result": "MATCH"}
        assert "E_MATCH_RESULT_FOREIGN_WRITER" in error_codes(graph)

    def test_no_extra_no_error(self):
        """Nodes without action.extra don't trigger the check."""
        graph = _minimal_valid()
        codes = error_codes(graph)
        assert "E_MATCH_RESULT_FOREIGN_WRITER" not in codes

    def test_production_graph_clean(self):
        """The valid match-split fixture has no foreign writers."""
        graph = _graph_with_valid_match_split()
        codes = error_codes(graph)
        assert "E_MATCH_RESULT_FOREIGN_WRITER" not in codes


class TestMatchResultRouting:
    """Tests for E_MATCH_RESULT_WRONG_ROUTER lint code."""

    def test_match_decision_gateway_ok(self):
        """MATCH_DECISION gateway routing on match_result is correct."""
        graph = _graph_with_valid_match_split()
        assert "E_MATCH_RESULT_WRONG_ROUTER" not in error_codes(graph)

    def test_task_routing_on_match_result_is_error(self):
        """A task node with match_result edge conditions → error.

        Regression guard for the n4 bug: VALIDATE_FIELDS task had
        match_result edges before MATCH_3_WAY had set the value.
        """
        graph = _graph_with_valid_match_split()
        # Add a task node n4 that routes on match_result (the old bug)
        graph["nodes"].append({
            "id": "n4", "kind": "task", "name": "Validate",
            "action": {"type": "VALIDATE_FIELDS", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:VALIDATE_FIELDS@n4"},
        })
        graph["edges"].append(
            {"frm": "n4", "to": "n_approve", "condition": 'match_result == "MATCH"'}
        )
        codes = error_codes(graph)
        assert "E_MATCH_RESULT_WRONG_ROUTER" in codes

    def test_non_match_decision_gateway_is_error(self):
        """A gateway routing on match_result but NOT MATCH_DECISION → error."""
        graph = _graph_with_valid_match_split()
        graph["nodes"].append({
            "id": "gw_other", "kind": "gateway", "name": "Other Gate",
            "action": None,
            "decision": {"type": "THRESHOLD_AMOUNT_10K", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:THRESHOLD@gw_other"},
        })
        graph["edges"].append(
            {"frm": "gw_other", "to": "n_approve", "condition": 'match_result == "MATCH"'}
        )
        assert "E_MATCH_RESULT_WRONG_ROUTER" in error_codes(graph)

    def test_edge_without_match_result_not_flagged(self):
        """Edges with other conditions are not flagged."""
        graph = _graph_with_valid_match_split()
        graph["edges"].append(
            {"frm": "n5", "to": "n_approve", "condition": "amount > 10000"}
        )
        assert "E_MATCH_RESULT_WRONG_ROUTER" not in error_codes(graph)


class TestMatchDecisionTruthTable:
    """Tests for E_MATCH_DECISION_TRUTH_TABLE lint code."""

    def test_valid_truth_table(self):
        """MATCH_DECISION gateway with exactly 3 canonical conditions → no error."""
        graph = _graph_with_valid_match_split()
        assert "E_MATCH_DECISION_TRUTH_TABLE" not in error_codes(graph)

    def test_missing_unknown_branch(self):
        """MATCH_DECISION gateway missing UNKNOWN edge → error."""
        graph = _graph_with_valid_match_split()
        # Remove the UNKNOWN edge
        graph["edges"] = [
            e for e in graph["edges"]
            if not (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "UNKNOWN"')
        ]
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_extra_edge(self):
        """MATCH_DECISION gateway with 4 edges (extra condition) → error."""
        graph = _graph_with_valid_match_split()
        graph["edges"].append({
            "frm": "n5_decision", "to": "n_approve",
            "condition": 'match_result == "VARIANCE"',
        })
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_duplicate_condition(self):
        """MATCH_DECISION gateway with duplicate MATCH edge → error."""
        graph = _graph_with_valid_match_split()
        # Replace UNKNOWN edge with a duplicate MATCH edge
        for e in graph["edges"]:
            if (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "UNKNOWN"'):
                e["condition"] = 'match_result == "MATCH"'
                break
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_non_match_decision_gateway_not_checked(self):
        """THRESHOLD gateway is not subject to truth table check."""
        graph = _graph_with_valid_match_split()
        graph["nodes"].append({
            "id": "gw_thresh", "kind": "gateway", "name": "Threshold",
            "action": None,
            "decision": {"type": "THRESHOLD_AMOUNT_10K", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:THRESHOLD@gw_thresh"},
        })
        graph["edges"].append({"frm": "gw_thresh", "to": "n_approve", "condition": "amount > 10000"})
        graph["edges"].append({"frm": "gw_thresh", "to": "n_end", "condition": "amount <= 10000"})
        assert "E_MATCH_DECISION_TRUTH_TABLE" not in error_codes(graph)

    def test_null_to_target(self):
        """Edge with null 'to' on MATCH_DECISION → error."""
        graph = _graph_with_valid_match_split()
        # Set the MATCH edge's target to None
        for e in graph["edges"]:
            if (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "MATCH"'):
                e["to"] = None
                break
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_dangling_to_target(self):
        """Edge pointing to a non-existent node on MATCH_DECISION → error."""
        graph = _graph_with_valid_match_split()
        # Point the MATCH edge at a node that doesn't exist
        for e in graph["edges"]:
            if (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "MATCH"'):
                e["to"] = "n_nonexistent"
                break
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_edge_count_mismatch(self):
        """4 edges with correct conditions + extra unconditional → error."""
        graph = _graph_with_valid_match_split()
        # Add a 4th unconditional edge from the decision gateway
        graph["edges"].append({
            "frm": "n5_decision", "to": "n_end", "condition": None,
        })
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_priority_field_on_edge(self):
        """Priority field on MATCH_DECISION edge → error."""
        graph = _graph_with_valid_match_split()
        for e in graph["edges"]:
            if (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "MATCH"'):
                e["priority"] = 1
                break
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_non_canonical_whitespace_variant(self):
        """Whitespace variant like 'match_result=="MATCH"' → error."""
        graph = _graph_with_valid_match_split()
        for e in graph["edges"]:
            if (e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "MATCH"'):
                e["condition"] = 'match_result=="MATCH"'
                break
        codes = error_codes(graph)
        assert "E_MATCH_DECISION_TRUTH_TABLE" in codes

    def test_valid_edges_have_existing_targets(self):
        """Valid graph: all MATCH_DECISION edge targets exist → no truth table error."""
        graph = _graph_with_valid_match_split()
        assert "E_MATCH_DECISION_TRUTH_TABLE" not in error_codes(graph)


# ===========================================================================
# Synthetic metadata completeness (check_synthetic_completeness)
# ===========================================================================

class TestSyntheticCompleteness:
    """Tests for E_SYNTHETIC_INCOMPLETE invariant."""

    def _base_graph(self, extra_nodes=None) -> dict:
        """Minimal valid graph, optionally with extra nodes appended."""
        g = _minimal_valid()
        if extra_nodes:
            for n in extra_nodes:
                g["nodes"].append(n)
        return g

    def test_no_synthetic_nodes_no_error(self):
        """Graph with no synthetic nodes → no E_SYNTHETIC_INCOMPLETE."""
        assert "E_SYNTHETIC_INCOMPLETE" not in error_codes(self._base_graph())

    def test_synthetic_missing_semantic_assumption(self):
        """meta.synthetic=True but no semantic_assumption → error."""
        node = {
            "id": "n_synth", "kind": "task", "name": "Synth",
            "action": {"type": "ENTER_RECORD", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {
                "canonical_key": "task:SYNTH",
                "synthetic": True,
                "origin_pass": "some_pass",
            },
        }
        assert "E_SYNTHETIC_INCOMPLETE" in error_codes(self._base_graph([node]))

    def test_synthetic_missing_origin_pass(self):
        """meta.synthetic=True but no origin_pass → error."""
        node = {
            "id": "n_synth", "kind": "task", "name": "Synth",
            "action": {"type": "ENTER_RECORD", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {
                "canonical_key": "task:SYNTH",
                "synthetic": True,
                "semantic_assumption": "some_assumption",
            },
        }
        assert "E_SYNTHETIC_INCOMPLETE" in error_codes(self._base_graph([node]))

    def test_synthetic_with_both_fields_no_error(self):
        """meta.synthetic=True with both fields → no E_SYNTHETIC_INCOMPLETE."""
        node = {
            "id": "n_synth", "kind": "task", "name": "Synth",
            "action": {"type": "ENTER_RECORD", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {
                "canonical_key": "task:SYNTH",
                "synthetic": True,
                "semantic_assumption": "some_assumption",
                "origin_pass": "some_pass",
            },
        }
        assert "E_SYNTHETIC_INCOMPLETE" not in error_codes(self._base_graph([node]))

    def test_synthetic_edges_entry_missing_origin_pass(self):
        """synthetic_edges entry without origin_pass → error."""
        node = {
            "id": "n_synth", "kind": "task", "name": "Synth",
            "action": {"type": "ENTER_RECORD", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {
                "canonical_key": "task:SYNTH",
                "synthetic_edges": [
                    {"to": "n2", "condition": "x == 1",
                     "semantic_assumption": "some_assumption"},
                ],
            },
        }
        assert "E_SYNTHETIC_INCOMPLETE" in error_codes(self._base_graph([node]))

    def test_synthetic_edges_entry_complete_no_error(self):
        """Complete synthetic_edges entry → no E_SYNTHETIC_INCOMPLETE."""
        node = {
            "id": "n_synth", "kind": "task", "name": "Synth",
            "action": {"type": "ENTER_RECORD", "actor_id": "role_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {
                "canonical_key": "task:SYNTH",
                "synthetic_edges": [
                    {"to": "n2", "condition": "x == 1",
                     "semantic_assumption": "some_assumption",
                     "origin_pass": "some_pass"},
                ],
            },
        }
        assert "E_SYNTHETIC_INCOMPLETE" not in error_codes(self._base_graph([node]))
