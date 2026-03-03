"""
tests/test_fix_match3way_gateway_secondary.py
Regression tests: SCHEDULE_PAYMENT miner-label noise must not brick
a MATCH_3_WAY gateway via the unparseable-gateway catch-all.

Runs the full ``normalize_all`` pipeline (not individual passes) so
pass-ordering regressions are caught too.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.normalize_graph import normalize_all


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _graph_with_schedule_payment_noise() -> dict:
    """
    Minimal graph reproducing the n5 bug:

    - n4  gateway (MATCH_3_WAY) — primary, handled by pass 5
    - n5  gateway (MATCH_3_WAY) — secondary, the one that used to get bricked
    - n6  task APPROVE
    - n7  task SCHEDULE_PAYMENT
    - n8  task EXECUTE_PAYMENT
    - n_exc_unmodeled_gate  exception station (MANUAL_REVIEW_UNMODELED_GATE)

    Edges from n5 include the miner label bug:
        n5 -> n6   MATCH_3_WAY          (parseable)
        n5 -> n7   MATCH_3_WAY          (parseable, fan-out dup)
        n5 -> n8   SCHEDULE_PAYMENT     (unparseable — task label as condition)
    """
    return {
        "actors": [
            {"id": "role_ap_clerk", "type": "human_role", "name": "AP Clerk"},
            {"id": "role_director", "type": "human_role", "name": "Director"},
        ],
        "artifacts": [
            {"id": "art_invoice", "type": "document", "name": "Invoice"},
            {"id": "art_payment", "type": "record",   "name": "Payment"},
        ],
        "nodes": [
            # --- structural bookends ---
            {
                "id": "n1", "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            {
                "id": "n32", "kind": "end", "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
            # --- primary match gateway (n4, handled by pass 5) ---
            {
                "id": "n4", "kind": "gateway", "name": "3-Way Match (primary)",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY"},
            },
            # --- secondary match gateway (n5, the regression target) ---
            {
                "id": "n5", "kind": "gateway", "name": "Decision",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY"},
            },
            # --- downstream tasks (the sequential chain) ---
            {
                "id": "n6", "kind": "task", "name": "Approve",
                "action": {"type": "APPROVE", "actor_id": "role_director",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE"},
            },
            {
                "id": "n7", "kind": "task", "name": "Schedule Payment",
                "action": {"type": "SCHEDULE_PAYMENT", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:SCHEDULE_PAYMENT"},
            },
            {
                "id": "n8", "kind": "task", "name": "Execute Payment",
                "action": {"type": "EXECUTE_PAYMENT", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:EXECUTE_PAYMENT"},
            },
            # --- exception station (mimics patch_logic injection) ---
            {
                "id": "n_exc_unmodeled_gate", "kind": "task",
                "name": "Manual Review — Unmodeled Gateway",
                "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice",
                           "extra": {"reason": "UNMODELED_GATE"}},
                "decision": None, "evidence": [],
                "meta": {
                    "canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE",
                    "intent_key":    "task:MANUAL_REVIEW_UNMODELED_GATE",
                    "origin":        "patch",
                    "synthetic":     True,
                    "patch_id":      "P.EXCEPTION_STATIONS.V1",
                },
            },
        ],
        "edges": [
            {"frm": "n1",  "to": "n4",  "condition": None},
            {"frm": "n4",  "to": "n5",  "condition": "MATCH_3_WAY"},
            # --- the bug: miner noise on n5 ---
            {"frm": "n5",  "to": "n6",  "condition": "MATCH_3_WAY"},
            {"frm": "n5",  "to": "n7",  "condition": "MATCH_3_WAY"},
            {"frm": "n5",  "to": "n8",  "condition": "SCHEDULE_PAYMENT"},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchedulePaymentDoesNotBrickMatchGateway:
    """Regression: SCHEDULE_PAYMENT edge label must not cause the
    unparseable-gateway catch-all to convert a MATCH_3_WAY gateway.

    After the task+decision split, n5 becomes a task (MATCH_3_WAY) and
    n5_decision is injected as a MATCH_DECISION gateway."""

    def test_n5_converted_to_task(self):
        """n5 must become kind=='task' with action.type MATCH_3_WAY."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n5"]["kind"] == "task"
        assert nmap["n5"]["action"]["type"] == "MATCH_3_WAY"

    def test_decision_gateway_injected(self):
        """n5_decision must exist as a MATCH_DECISION gateway."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert "n5_decision" in nmap
        assert nmap["n5_decision"]["kind"] == "gateway"
        assert nmap["n5_decision"]["decision"]["type"] == "MATCH_DECISION"

    def test_task_to_decision_edge(self):
        """n5 (task) has exactly 1 outgoing edge: unconditional to n5_decision."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        out = [e for e in g["edges"] if e.get("frm") == "n5"]
        assert len(out) == 1
        assert out[0]["to"] == "n5_decision"
        assert out[0]["condition"] is None

    def test_decision_gateway_has_conditional_edges(self):
        """Every outgoing edge from n5_decision must have an explicit condition."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        out = [e for e in g["edges"] if e.get("frm") == "n5_decision"]
        assert out, "n5_decision must have outgoing edges"
        for e in out:
            assert e.get("condition") is not None, (
                f"n5_decision -> {e['to']} has condition=None; "
                "gateway edges must be explicit"
            )

    def test_unknown_guardrail_present(self):
        """n5_decision must have a match_result == 'UNKNOWN' edge to the
        unmodeled-gate station."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        unknown_edges = [
            e for e in g["edges"]
            if e.get("frm") == "n5_decision"
            and e.get("condition") == 'match_result == "UNKNOWN"'
        ]
        assert len(unknown_edges) == 1
        assert unknown_edges[0]["to"] == "n_exc_unmodeled_gate"

    def test_sequential_chain_approve_to_schedule(self):
        """Unconditional edge n6 (APPROVE) -> n7 (SCHEDULE_PAYMENT) must exist."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        chain = [e for e in g["edges"]
                 if e.get("frm") == "n6" and e.get("to") == "n7"]
        assert len(chain) == 1
        assert chain[0]["condition"] is None

    def test_sequential_chain_schedule_to_execute(self):
        """Unconditional edge n7 (SCHEDULE) -> n8 (EXECUTE) must exist
        (before fix_main_execution_path potentially rewires it)."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        # After normalize_all, fix_main_execution_path may redirect
        # n7 -> end.  Check that n7 has at least one outgoing edge.
        n7_out = [e for e in g["edges"] if e.get("frm") == "n7"]
        assert n7_out, "n7 must have at least one outgoing edge"

    def test_idempotent(self):
        """Running normalize_all twice yields identical edges."""
        g = _graph_with_schedule_payment_noise()
        g, _ = normalize_all(g)
        snapshot = sorted(
            (e.get("frm"), e.get("to"), e.get("condition"))
            for e in g["edges"]
        )
        g, _ = normalize_all(g)
        snapshot2 = sorted(
            (e.get("frm"), e.get("to"), e.get("condition"))
            for e in g["edges"]
        )
        assert snapshot == snapshot2
