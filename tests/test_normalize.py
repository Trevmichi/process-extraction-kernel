"""
tests/test_normalize.py
Unit tests for src/normalize_graph.py normalization passes.

Each pass is tested for:
- Correct transformation of the known bad patterns
- Idempotency (running twice yields the same result)
- No-op when preconditions are already satisfied
"""
from __future__ import annotations

import copy

import pytest

from src.normalize_graph import (
    convert_fanout_gateways_to_ambiguous_station,
    convert_unparseable_gateways_to_station,
    convert_whitelisted_fanout_to_sequential,
    deduplicate_edges,
    deduplicate_edges_strict,
    fix_artifact_references,
    fix_canonical_key_duplicates,
    fix_haspo_gateway,
    fix_main_execution_path,
    fix_match3way_gateway,
    fix_placeholder_gateways,
    fix_secondary_match_gateways,
    inject_exception_nodes,
    inject_match_result_unknown_guardrail,
    normalize_all,
    normalize_edge_conditions,
    wire_bad_extraction_route,
)
from src.agent.router import route_edge


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _minimal() -> dict:
    """A very small graph that exercises the critical paths of every pass."""
    return {
        "actors": [
            {"id": "role_ap_clerk", "type": "human_role", "name": "AP Clerk"},
        ],
        "artifacts": [
            {"id": "art_invoice", "type": "document", "name": "Invoice"},
            {"id": "art_po",      "type": "record",   "name": "PO"},
        ],
        "nodes": [
            {
                "id": "n1", "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            {
                "id": "n3", "kind": "task", "name": "Validate Fields",
                "action": {
                    "type": "VALIDATE_FIELDS", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:VALIDATE_FIELDS"},
            },
            {
                "id": "n4", "kind": "gateway", "name": "3-Way Match",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY"},
            },
            {
                "id": "n5", "kind": "task", "name": "Approve",
                "action": {
                    "type": "APPROVE", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE"},
            },
            {
                "id": "n32", "kind": "end", "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
        ],
        "edges": [
            {"frm": "n1",  "to": "n3",  "condition": None},
            {"frm": "n3",  "to": "n4",  "condition": None},
            {"frm": "n4",  "to": "n5",  "condition": "MATCH_3_WAY"},
            {"frm": "n5",  "to": "n32", "condition": None},
        ],
    }


def _graph_with_n8_fanout() -> dict:
    """Graph where n8 has 6 fan-out edges all with 'HAS_PO' condition."""
    g = _minimal()
    # Add n8 (HAS_PO gateway) and targets n9, n15, n32
    g["nodes"].extend([
        {
            "id": "n8", "kind": "gateway", "name": "HAS_PO",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO"},
        },
        {
            "id": "n9",  "kind": "task", "name": "MANAGER_APPROVE",
            "action": {"type": "MANAGER_APPROVE", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANAGER_APPROVE"},
        },
        {
            "id": "n10", "kind": "task", "name": "DIRECTOR_APPROVE",
            "action": {"type": "DIRECTOR_APPROVE", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:DIRECTOR_APPROVE"},
        },
        {
            "id": "n11", "kind": "task", "name": "NOTIFY_VENDOR",
            "action": {"type": "NOTIFY_VENDOR", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:NOTIFY_VENDOR"},
        },
        {
            "id": "n12", "kind": "task", "name": "SEND_PAYMENT",
            "action": {"type": "SEND_PAYMENT", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:SEND_PAYMENT"},
        },
        {
            "id": "n15", "kind": "task", "name": "MATCH",
            "action": {"type": "MATCH", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MATCH"},
        },
    ])
    # 6 fan-out edges — all same condition
    for target in ["n9", "n10", "n11", "n12", "n15", "n32"]:
        g["edges"].append({"frm": "n8", "to": target, "condition": "HAS_PO"})
    return g


def _graph_with_n7_to_n8() -> dict:
    """Graph where n7 (EXECUTE_PAYMENT) incorrectly wires to n8."""
    g = _minimal()
    g["nodes"].extend([
        {
            "id": "n7",  "kind": "task", "name": "EXECUTE_PAYMENT",
            "action": {"type": "EXECUTE_PAYMENT", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:EXECUTE_PAYMENT"},
        },
        {
            "id": "n8", "kind": "gateway", "name": "HAS_PO",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO"},
        },
    ])
    g["edges"].append({"frm": "n7", "to": "n8", "condition": None})
    return g


# ===========================================================================
# Pass 1 — fix_artifact_references
# ===========================================================================

class TestFixArtifactReferences:

    def test_injects_art_account_code_when_absent(self):
        g = _minimal()
        ids_before = {a["id"] for a in g["artifacts"]}
        assert "art_account_code" not in ids_before
        g, log = fix_artifact_references(g)
        ids_after = {a["id"] for a in g["artifacts"]}
        assert "art_account_code" in ids_after

    def test_does_not_duplicate_art_account_code(self):
        g = _minimal()
        g["artifacts"].append({"id": "art_account_code", "type": "record", "name": "GL Account Code"})
        g, _ = fix_artifact_references(g)
        count = sum(1 for a in g["artifacts"] if a["id"] == "art_account_code")
        assert count == 1

    def test_idempotent(self):
        g = _minimal()
        g, _ = fix_artifact_references(g)
        g, _ = fix_artifact_references(g)
        count = sum(1 for a in g["artifacts"] if a["id"] == "art_account_code")
        assert count == 1

    def test_fixes_receive_message_empty_artifact_id(self):
        g = _minimal()
        g["nodes"].append({
            "id": "n19", "kind": "task", "name": "RECEIVE_MESSAGE",
            "action": {"type": "RECEIVE_MESSAGE", "actor_id": "role_ap_clerk",
                       "artifact_id": "", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:RECEIVE_MESSAGE"},
        })
        g, log = fix_artifact_references(g)
        n19 = next(n for n in g["nodes"] if n["id"] == "n19")
        assert n19["action"]["artifact_id"] == "art_invoice"

    def test_log_mentions_injection(self):
        g = _minimal()
        _, log = fix_artifact_references(g)
        assert any("art_account_code" in line for line in log)


# ===========================================================================
# Pass 2 — fix_canonical_key_duplicates
# ===========================================================================

class TestFixCanonicalKeyDuplicates:

    def _graph_with_dup_keys(self) -> dict:
        g = _minimal()
        # Add two more nodes with same canonical_key as n5
        for nid in ("n22", "n23"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Approve copy {nid}",
                "action": {"type": "APPROVE", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE"},
            })
        return g

    def test_dup_keys_are_suffixed(self):
        g = self._graph_with_dup_keys()
        g, _ = fix_canonical_key_duplicates(g)
        keys = [(n["id"], n["meta"]["canonical_key"]) for n in g["nodes"]]
        ckeys = [k for _, k in keys if "APPROVE" in k]
        # All should now be unique
        assert len(ckeys) == len(set(ckeys))

    def test_intent_key_set_for_all_nodes(self):
        g = self._graph_with_dup_keys()
        g, _ = fix_canonical_key_duplicates(g)
        for node in g["nodes"]:
            if (node.get("meta") or {}).get("canonical_key"):
                assert "intent_key" in node["meta"]

    def test_no_change_when_keys_unique(self):
        g = _minimal()
        g, log = fix_canonical_key_duplicates(g)
        # No renames should appear in log
        assert not any("->" in line for line in log)

    def test_idempotent(self):
        g = self._graph_with_dup_keys()
        g, _ = fix_canonical_key_duplicates(g)
        keys_after_1 = {n["id"]: n["meta"]["canonical_key"] for n in g["nodes"]}
        g, _ = fix_canonical_key_duplicates(g)
        keys_after_2 = {n["id"]: n["meta"]["canonical_key"] for n in g["nodes"]}
        assert keys_after_1 == keys_after_2


# ===========================================================================
# Pass 3 — normalize_edge_conditions
# ===========================================================================

class TestNormalizeEdgeConditions:

    def test_match_3_way_synonym_normalized(self):
        g = _minimal()
        g, _ = normalize_edge_conditions(g)
        conditions = {e.get("condition") for e in g["edges"]}
        # "MATCH_3_WAY" -> 'match_result == "MATCH"'
        assert 'match_result == "MATCH"' in conditions
        assert "MATCH_3_WAY" not in conditions

    def test_null_conditions_unchanged(self):
        g = _minimal()
        g, _ = normalize_edge_conditions(g)
        null_edges = [e for e in g["edges"] if e.get("condition") is None]
        assert len(null_edges) > 0

    def test_already_canonical_unchanged(self):
        g = _minimal()
        # Pre-normalize
        for e in g["edges"]:
            if e.get("condition") == "MATCH_3_WAY":
                e["condition"] = "match_3_way == true"
        g, log = normalize_edge_conditions(g)
        # No log entries (nothing changed)
        assert log == []

    def test_idempotent(self):
        g = _minimal()
        g, _ = normalize_edge_conditions(g)
        conds_1 = [e.get("condition") for e in g["edges"]]
        g, _ = normalize_edge_conditions(g)
        conds_2 = [e.get("condition") for e in g["edges"]]
        assert conds_1 == conds_2


# ===========================================================================
# Pass 4 — inject_exception_nodes
# ===========================================================================

class TestInjectExceptionNodes:

    def test_injects_n_no_match(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        ids = {n["id"] for n in g["nodes"]}
        assert "n_no_match" in ids

    def test_injects_n_manual_review_gate(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        ids = {n["id"] for n in g["nodes"]}
        assert "n_manual_review_gate" in ids

    def test_injected_nodes_have_correct_intent(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_no_match"]["action"]["type"] == "MANUAL_REVIEW_MATCH_FAILED"
        assert nmap["n_manual_review_gate"]["action"]["type"] == "MANUAL_REVIEW_UNMODELED_GATE"

    def test_idempotent(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        ids_after_1 = {n["id"] for n in g["nodes"]}
        g, _ = inject_exception_nodes(g)
        ids_after_2 = {n["id"] for n in g["nodes"]}
        assert ids_after_1 == ids_after_2

    def test_injected_node_has_origin_normalize(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_no_match"]["meta"]["origin"] == "normalize"


# ===========================================================================
# Pass 5 — fix_match3way_gateway
# ===========================================================================

class TestFixMatch3wayGateway:

    def _graph_with_n4_fanout(self) -> dict:
        g = _minimal()
        # Inject n_no_match and n_threshold (needed as targets)
        g["nodes"].extend([
            {
                "id": "n_no_match", "kind": "task", "name": "Manual Review",
                "action": {"type": "MANUAL_REVIEW_MATCH_FAILED", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_MATCH_FAILED@n_no_match",
                         "origin": "normalize"},
            },
            {
                "id": "n_threshold", "kind": "gateway", "name": "Threshold",
                "action": None, "decision": {"type": "THRESHOLD_AMOUNT_10K",
                                              "inputs": [], "expression": None},
                "evidence": [], "meta": {"canonical_key": "gw:THRESHOLD_AMOUNT_10K"},
            },
        ])
        # n4 has multiple edges with same condition (fan-out)
        g["edges"].extend([
            {"frm": "n4", "to": "n_threshold", "condition": "MATCH_3_WAY"},
            {"frm": "n4", "to": "n5",          "condition": "MATCH_3_WAY"},
            {"frm": "n4", "to": "n32",         "condition": "SCHEDULE_PAYMENT"},
        ])
        return g

    def test_fanout_reduced_to_two_branches(self):
        g = self._graph_with_n4_fanout()
        g, _ = fix_match3way_gateway(g)
        out = [e for e in g["edges"] if e.get("frm") == "n4"]
        assert len(out) == 2

    def test_true_branch_present(self):
        g = self._graph_with_n4_fanout()
        g, _ = fix_match3way_gateway(g)
        out = [e for e in g["edges"] if e.get("frm") == "n4"]
        conds = {e["condition"] for e in out}
        assert 'match_result == "MATCH"' in conds

    def test_false_branch_to_no_match(self):
        g = self._graph_with_n4_fanout()
        g, _ = fix_match3way_gateway(g)
        false_edges = [e for e in g["edges"]
                       if e.get("frm") == "n4" and e.get("condition") == 'match_result == "NO_MATCH"']
        assert len(false_edges) == 1
        assert false_edges[0]["to"] == "n_no_match"

    def test_idempotent(self):
        g = self._graph_with_n4_fanout()
        g, _ = fix_match3way_gateway(g)
        out_1 = sorted((e["to"], e["condition"]) for e in g["edges"] if e.get("frm") == "n4")
        g, _ = fix_match3way_gateway(g)
        out_2 = sorted((e["to"], e["condition"]) for e in g["edges"] if e.get("frm") == "n4")
        assert out_1 == out_2

    def test_noop_when_already_correct(self):
        g = _minimal()
        # Remove existing n4 edges and put correct 2-branch structure
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n4"]
        g["nodes"].extend([
            {"id": "n_no_match", "kind": "task", "name": "X",
             "action": {"type": "MANUAL_REVIEW_MATCH_FAILED", "actor_id": "role_ap_clerk",
                        "artifact_id": "art_invoice", "extra": {}},
             "decision": None, "evidence": [], "meta": {"canonical_key": "x"}},
            {"id": "n_threshold", "kind": "gateway", "name": "Y",
             "action": None, "decision": {"type": "T", "inputs": [], "expression": None},
             "evidence": [], "meta": {"canonical_key": "y"}},
        ])
        g["edges"].extend([
            {"frm": "n4", "to": "n_threshold", "condition": 'match_result == "MATCH"'},
            {"frm": "n4", "to": "n_no_match",  "condition": 'match_result == "NO_MATCH"'},
        ])
        g, log = fix_match3way_gateway(g)
        assert any("already" in line for line in log)


# ===========================================================================
# Pass 5b — fix_secondary_match_gateways
# ===========================================================================

class TestFixSecondaryMatchGateways:
    """Tests for fix_secondary_match_gateways (pass 5b)."""

    def _stations(self) -> list[dict]:
        """Return station nodes required by the pass."""
        return [
            {
                "id": "n_no_match", "kind": "task",
                "name": "Manual Review — Match Failed",
                "action": {"type": "MANUAL_REVIEW_MATCH_FAILED",
                           "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_MATCH_FAILED@n_no_match",
                         "intent_key": "task:MANUAL_REVIEW_MATCH_FAILED"},
            },
            {
                "id": "n_manual_review_gate", "kind": "task",
                "name": "Manual Review — Unmodeled Gate",
                "action": {"type": "MANUAL_REVIEW_UNMODELED_GATE",
                           "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_manual_review_gate",
                         "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
            },
        ]

    def _graph_with_n5_noise(self) -> dict:
        """
        Minimal graph with n5 as a secondary MATCH_3_WAY gateway exhibiting
        miner noise: fan-out MATCH edges + a SCHEDULE_PAYMENT label edge.
        """
        g = _minimal()
        # Override n5 to be a gateway (in _minimal it's a task:APPROVE)
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n5"]
        g["nodes"].extend([
            {
                "id": "n5", "kind": "gateway", "name": "Decision",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY@n5",
                         "intent_key": "gw:MATCH_3_WAY"},
            },
            {
                "id": "n6", "kind": "task", "name": "Approve",
                "action": {"type": "APPROVE", "actor_id": "role_director",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE@n6",
                         "intent_key": "task:APPROVE"},
            },
            {
                "id": "n7", "kind": "task", "name": "Schedule Payment",
                "action": {"type": "SCHEDULE_PAYMENT", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:SCHEDULE_PAYMENT@n7"},
            },
            {
                "id": "n8", "kind": "task", "name": "Execute Payment",
                "action": {"type": "EXECUTE_PAYMENT", "actor_id": "sys_erp",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:EXECUTE_PAYMENT@n8"},
            },
            *self._stations(),
        ])
        # Replace n5 outgoing edge — add miner noise edges
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n5"]
        g["edges"].extend([
            {"frm": "n5", "to": "n6", "condition": "MATCH_3_WAY"},       # → APPROVE
            {"frm": "n5", "to": "n7", "condition": "MATCH_3_WAY"},       # fan-out dup
            {"frm": "n5", "to": "n8", "condition": "SCHEDULE_PAYMENT"},  # miner label noise
            {"frm": "n5", "to": "n6", "condition": "match"},             # another dup
        ])
        return g

    def test_n5_converted_to_task(self):
        """After repair, n5 is a task with action.type MATCH_3_WAY."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n5"]["kind"] == "task"
        assert nmap["n5"]["action"]["type"] == "MATCH_3_WAY"
        assert nmap["n5"]["decision"] is None

    def test_decision_gateway_injected(self):
        """After repair, n5_decision exists as a MATCH_DECISION gateway."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert "n5_decision" in nmap
        assert nmap["n5_decision"]["kind"] == "gateway"
        assert nmap["n5_decision"]["decision"]["type"] == "MATCH_DECISION"

    def test_task_to_decision_edge(self):
        """n5 (task) has exactly 1 outgoing edge: unconditional to n5_decision."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n5"]
        assert len(out) == 1
        assert out[0]["to"] == "n5_decision"
        assert out[0]["condition"] is None

    def test_three_branch_structure(self):
        """After repair, n5_decision has exactly 3 canonical branch edges."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n5_decision"]
        assert len(out) == 3
        conds = {e["condition"] for e in out}
        assert conds == {
            'match_result == "MATCH"',
            'match_result == "NO_MATCH"',
            'match_result == "UNKNOWN"',
        }

    def test_match_branch_prefers_approve(self):
        """MATCH branch targets the APPROVE node (n6) over SCHEDULE_PAYMENT."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        match_edges = [e for e in g["edges"]
                       if e.get("frm") == "n5_decision"
                       and e.get("condition") == 'match_result == "MATCH"']
        assert len(match_edges) == 1
        assert match_edges[0]["to"] == "n6"

    def test_no_match_branch_target(self):
        """NO_MATCH branch routes to n_no_match station."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        no_match = [e for e in g["edges"]
                    if e.get("frm") == "n5_decision"
                    and e.get("condition") == 'match_result == "NO_MATCH"']
        assert len(no_match) == 1
        assert no_match[0]["to"] == "n_no_match"

    def test_unknown_branch_target(self):
        """UNKNOWN branch routes to unmodeled-gate station."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        unknown = [e for e in g["edges"]
                   if e.get("frm") == "n5_decision"
                   and e.get("condition") == 'match_result == "UNKNOWN"']
        assert len(unknown) == 1
        assert unknown[0]["to"] == "n_manual_review_gate"

    def test_noise_edges_removed_from_task(self):
        """Task (formerly gateway) only connects to decision gateway."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        task_targets = {e["to"] for e in g["edges"] if e.get("frm") == "n5"}
        assert task_targets == {"n5_decision"}

    def test_provenance_meta(self):
        """Injected edges carry normalize provenance."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        # task → decision edge
        for e in g["edges"]:
            if e.get("frm") == "n5":
                assert e.get("meta", {}).get("origin") == "normalize"
                assert "secondary_match" in e.get("meta", {}).get("patch_id", "")
        # decision → branch edges
        for e in g["edges"]:
            if e.get("frm") == "n5_decision":
                assert e.get("meta", {}).get("origin") == "normalize"
                assert "secondary_match" in e.get("meta", {}).get("patch_id", "")

    def test_idempotent(self):
        """Running twice produces the same edges."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        edges_1 = sorted(
            (e.get("frm"), e["to"], e.get("condition"))
            for e in g["edges"]
            if e.get("frm") in ("n5", "n5_decision")
        )
        g, _ = fix_secondary_match_gateways(g)
        edges_2 = sorted(
            (e.get("frm"), e["to"], e.get("condition"))
            for e in g["edges"]
            if e.get("frm") in ("n5", "n5_decision")
        )
        assert edges_1 == edges_2

    def test_noop_when_already_split(self):
        """After split, n5 is kind='task' — second run finds no gateways."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        g, log = fix_secondary_match_gateways(g)
        # n5 is now a task, so _is_match3way_gateway returns False → empty log
        assert log == []

    def test_skips_n4(self):
        """n4 is NOT touched by this pass (handled by fix_match3way_gateway)."""
        g = self._graph_with_n5_noise()
        original_n4_edges = [e for e in g["edges"] if e.get("frm") == "n4"]
        g, _ = fix_secondary_match_gateways(g)
        after_n4_edges = [e for e in g["edges"] if e.get("frm") == "n4"]
        assert original_n4_edges == after_n4_edges

    def test_raises_if_no_match_station_missing(self):
        """ValueError if MANUAL_REVIEW_MATCH_FAILED station is absent."""
        g = self._graph_with_n5_noise()
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n_no_match"]
        with pytest.raises(ValueError, match="MANUAL_REVIEW_MATCH_FAILED"):
            fix_secondary_match_gateways(g)

    def test_raises_if_unmodeled_station_missing(self):
        """ValueError if MANUAL_REVIEW_UNMODELED_GATE station is absent."""
        g = self._graph_with_n5_noise()
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n_manual_review_gate"]
        with pytest.raises(ValueError, match="MANUAL_REVIEW_UNMODELED_GATE"):
            fix_secondary_match_gateways(g)

    def test_noop_when_no_secondary_gateways(self):
        """Pass does nothing if no secondary MATCH_3_WAY gateways exist."""
        g = _minimal()
        g, log = fix_secondary_match_gateways(g)
        assert log == []

    def test_detects_by_decision_type(self):
        """Gateway found via decision.type even without intent_key."""
        g = self._graph_with_n5_noise()
        # Remove intent_key / canonical_key signals, keep decision.type
        for n in g["nodes"]:
            if n["id"] == "n5":
                n["meta"] = {"canonical_key": "gw:SOMETHING_ELSE"}
        g, _ = fix_secondary_match_gateways(g)
        # n5 should be converted to task with 1 edge to n5_decision
        out_n5 = [e for e in g["edges"] if e.get("frm") == "n5"]
        assert len(out_n5) == 1
        assert out_n5[0]["to"] == "n5_decision"
        # n5_decision should have 3 branch edges
        out_dec = [e for e in g["edges"] if e.get("frm") == "n5_decision"]
        assert len(out_dec) == 3

    def test_fail_closed_when_approve_missing(self):
        """If APPROVE node is missing, chain is incomplete → fail-closed."""
        g = self._graph_with_n5_noise()
        # Change n6's action so it's no longer APPROVE
        for n in g["nodes"]:
            if n["id"] == "n6":
                n["action"]["type"] = "SOME_OTHER_TASK"
        g, log = fix_secondary_match_gateways(g)
        match_edge = [e for e in g["edges"]
                      if e.get("frm") == "n5_decision"
                      and e.get("condition") == 'match_result == "MATCH"']
        assert len(match_edge) == 1
        # Incomplete chain → MATCH branch routes to unmodeled station
        assert match_edge[0]["to"] == "n_manual_review_gate"
        assert any("incomplete chain" in line for line in log)

    def test_fail_closed_when_schedule_missing(self):
        """If SCHEDULE_PAYMENT node is absent, chain is incomplete → fail-closed."""
        g = self._graph_with_n5_noise()
        # Remove n7 (SCHEDULE_PAYMENT) from nodes and edges
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n7"]
        g["edges"] = [e for e in g["edges"] if e.get("to") != "n7" and e.get("frm") != "n7"]
        g, log = fix_secondary_match_gateways(g)
        match_edge = [e for e in g["edges"]
                      if e.get("frm") == "n5_decision"
                      and e.get("condition") == 'match_result == "MATCH"']
        assert len(match_edge) == 1
        assert match_edge[0]["to"] == "n_manual_review_gate"
        assert any("SCHEDULE_PAYMENT" in line for line in log)

    def test_fail_closed_when_execute_missing(self):
        """If EXECUTE_PAYMENT node is absent, chain is incomplete → fail-closed."""
        g = self._graph_with_n5_noise()
        # Remove n8 (EXECUTE_PAYMENT) from nodes and edges
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n8"]
        g["edges"] = [e for e in g["edges"] if e.get("to") != "n8" and e.get("frm") != "n8"]
        g, log = fix_secondary_match_gateways(g)
        match_edge = [e for e in g["edges"]
                      if e.get("frm") == "n5_decision"
                      and e.get("condition") == 'match_result == "MATCH"']
        assert len(match_edge) == 1
        assert match_edge[0]["to"] == "n_manual_review_gate"
        assert any("EXECUTE_PAYMENT" in line for line in log)

    # --- Phase 2: sequential chain tests ---

    def test_chain_approve_to_schedule(self):
        """Phase 2 wires n6 (APPROVE) -> n7 (SCHEDULE_PAYMENT)."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        chain = [e for e in g["edges"]
                 if e.get("frm") == "n6" and e.get("to") == "n7"]
        assert len(chain) == 1
        assert chain[0]["condition"] is None

    def test_chain_schedule_to_execute(self):
        """Phase 2 wires n7 (SCHEDULE_PAYMENT) -> n8 (EXECUTE_PAYMENT)."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        chain = [e for e in g["edges"]
                 if e.get("frm") == "n7" and e.get("to") == "n8"]
        assert len(chain) == 1
        assert chain[0]["condition"] is None

    def test_chain_edges_have_provenance(self):
        """Chain edges carry normalize provenance metadata."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        for frm, to in [("n6", "n7"), ("n7", "n8")]:
            edge = next(e for e in g["edges"]
                        if e.get("frm") == frm and e.get("to") == to)
            assert edge["meta"]["origin"] == "normalize"
            assert "secondary_match" in edge["meta"]["patch_id"]

    def test_chain_not_wired_when_incomplete(self):
        """If chain is incomplete (fail-closed), no chain edges are injected."""
        g = self._graph_with_n5_noise()
        # Remove EXECUTE_PAYMENT → chain incomplete
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n8"]
        g["edges"] = [e for e in g["edges"] if e.get("to") != "n8" and e.get("frm") != "n8"]
        g, _ = fix_secondary_match_gateways(g)
        # No chain edges should exist
        assert not any(e.get("frm") == "n6" and e.get("to") == "n7" for e in g["edges"])
        assert not any(e.get("frm") == "n7" and e.get("to") == "n8" for e in g["edges"])

    def test_chain_idempotent(self):
        """Running twice doesn't duplicate chain edges."""
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        chain_count_1 = sum(
            1 for e in g["edges"]
            if (e.get("frm") == "n6" and e.get("to") == "n7")
            or (e.get("frm") == "n7" and e.get("to") == "n8")
        )
        g, _ = fix_secondary_match_gateways(g)
        chain_count_2 = sum(
            1 for e in g["edges"]
            if (e.get("frm") == "n6" and e.get("to") == "n7")
            or (e.get("frm") == "n7" and e.get("to") == "n8")
        )
        assert chain_count_1 == 2
        assert chain_count_2 == 2

    def test_chain_skips_existing_edges(self):
        """If chain edges already exist, log indicates 'already present'."""
        g = self._graph_with_n5_noise()
        # Pre-wire one chain edge
        g["edges"].append({"frm": "n6", "to": "n7", "condition": None})
        g, log = fix_secondary_match_gateways(g)
        assert any("n6->n7 already present" in line for line in log)
        # But n7->n8 should be newly wired
        assert any("wired chain n7->n8" in line for line in log)


# ===========================================================================
# Pass 6 — fix_main_execution_path
# ===========================================================================

class TestFixMainExecutionPath:

    def test_removes_n7_to_n8(self):
        g = _graph_with_n7_to_n8()
        g, _ = fix_main_execution_path(g)
        bad = [e for e in g["edges"] if e.get("frm") == "n7" and e.get("to") == "n8"]
        assert bad == []

    def test_adds_n7_to_end(self):
        g = _graph_with_n7_to_n8()
        g, _ = fix_main_execution_path(g)
        to_end = [e for e in g["edges"] if e.get("frm") == "n7" and e.get("to") == "n32"]
        assert len(to_end) == 1

    def test_idempotent(self):
        g = _graph_with_n7_to_n8()
        g, _ = fix_main_execution_path(g)
        edges_after_1 = [(e["frm"], e["to"]) for e in g["edges"]]
        g, _ = fix_main_execution_path(g)
        edges_after_2 = [(e["frm"], e["to"]) for e in g["edges"]]
        assert edges_after_1 == edges_after_2

    def test_noop_when_no_n7(self):
        g = _minimal()
        g, log = fix_main_execution_path(g)
        # n7 does not exist — should either report noop or skip silently
        assert "n7" not in str(log) or "Already" in str(log) or log == []


# ===========================================================================
# Pass 7 — fix_haspo_gateway
# ===========================================================================

class TestFixHaspoGateway:

    def test_fanout_reduced_to_two_branches(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        out = [e for e in g["edges"] if e.get("frm") == "n8"]
        assert len(out) == 2

    def test_true_branch_to_n15(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        true_edges = [e for e in g["edges"]
                      if e.get("frm") == "n8" and e.get("condition") == "has_po == true"]
        assert len(true_edges) == 1
        assert true_edges[0]["to"] == "n15"

    def test_false_branch_to_n9(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        false_edges = [e for e in g["edges"]
                       if e.get("frm") == "n8" and e.get("condition") == "has_po == false"]
        assert len(false_edges) == 1
        assert false_edges[0]["to"] == "n9"

    def test_sequential_chain_n9_to_n10(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        chain = [e for e in g["edges"] if e.get("frm") == "n9" and e.get("to") == "n10"]
        assert len(chain) == 1

    def test_n12_wired_to_end(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        end_edges = [e for e in g["edges"] if e.get("frm") == "n12" and e.get("to") == "n32"]
        assert len(end_edges) == 1

    def test_idempotent(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        out_1 = sorted((e["frm"], e["to"], e.get("condition")) for e in g["edges"])
        g, _ = fix_haspo_gateway(g)
        out_2 = sorted((e["frm"], e["to"], e.get("condition")) for e in g["edges"])
        assert out_1 == out_2


# ===========================================================================
# Pass 8 — fix_placeholder_gateways
# ===========================================================================

class TestFixPlaceholderGateways:

    def _graph_with_n16_n28(self) -> dict:
        g = _minimal()
        # Add n_manual_review_gate target
        g["nodes"].append({
            "id": "n_manual_review_gate", "kind": "task", "name": "Manual Review Gate",
            "action": {"type": "MANUAL_REVIEW_UNMODELED_GATE", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_manual_review_gate",
                     "origin": "normalize"},
        })
        # n16: unmodeled gateway with IF_CONDITION
        g["nodes"].append({
            "id": "n16", "kind": "gateway", "name": "Variance OK?",
            "action": None,
            "decision": {"type": "IF_CONDITION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:IF_CONDITION@n16"},
        })
        g["edges"].extend([
            {"frm": "n5",  "to": "n16", "condition": None},
            {"frm": "n16", "to": "n5",  "condition": "IF_CONDITION"},
            {"frm": "n16", "to": "n32", "condition": "IF_CONDITION"},
        ])
        # n28: duplicate check gateway
        for nid in ("n28", "n29", "n30", "n31"):
            g["nodes"].append({
                "id": nid, "kind": "gateway" if nid == "n28" else "task",
                "name": f"Node {nid}",
                "action": None if nid == "n28" else {
                    "type": "TASK_X", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": ({"type": "IF_CONDITION", "inputs": [], "expression": None}
                             if nid == "n28" else None),
                "evidence": [],
                "meta": {"canonical_key": f"gw:duplicate@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n28", "to": "n29", "condition": "IF_CONDITION"},
            {"frm": "n28", "to": "n30", "condition": "IF_CONDITION"},
            {"frm": "n28", "to": "n31", "condition": "MATCH_3_WAY"},
        ])
        return g

    def test_n16_converted_to_task(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n16"]["kind"] == "task"
        assert nmap["n16"]["action"]["type"] == "MANUAL_REVIEW_UNMODELED_GATE"

    def test_n16_outgoing_edges_removed(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n16"
               and e.get("to") != "n_manual_review_gate"]
        assert out == []

    def test_n16_routes_to_manual_review_gate(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n16"]
        assert len(out) == 1
        assert out[0]["to"] == "n_manual_review_gate"

    def test_n28_has_explicit_conditions(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n28"]
        conds = {e.get("condition") for e in out}
        assert 'status == "DUPLICATE"' in conds
        assert 'status != "DUPLICATE"' in conds

    def test_n30_n31_sequential_edge_added(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        chain = [e for e in g["edges"] if e.get("frm") == "n30" and e.get("to") == "n31"]
        assert len(chain) == 1

    def test_idempotent_exception_conversion(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        n16_kind_1 = next(n["kind"] for n in g["nodes"] if n["id"] == "n16")
        g, _ = fix_placeholder_gateways(g)
        n16_kind_2 = next(n["kind"] for n in g["nodes"] if n["id"] == "n16")
        assert n16_kind_1 == n16_kind_2 == "task"


# ===========================================================================
# Pass 9 — convert_unparseable_gateways_to_station
# ===========================================================================

class TestConvertUnparseableGatewaysToStation:

    def _graph_with_unparseable_gateway(self) -> dict:
        """Graph with a gateway (n_gw) that has IF_CONDITION edges."""
        g = _minimal()
        # Add station node that the pass routes to
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Exception — Unmodeled Gate",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {"reason": "UNMODELED_GATE"}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc_unmodeled_gate",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # Add unparseable gateway
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Unknown Decision",
            "action": None,
            "decision": {"type": "IF_CONDITION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:IF_CONDITION@n_gw"},
        })
        # Targets for the gateway
        for nid in ("n_a", "n_b"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {nid}",
                "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:X@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n5",   "to": "n_gw", "condition": None},
            {"frm": "n_gw", "to": "n_a",  "condition": "IF_CONDITION"},
            {"frm": "n_gw", "to": "n_b",  "condition": "IF_CONDITION"},
        ])
        return g

    def test_converts_gateway_to_task(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"
        assert nmap["n_gw"]["action"]["type"] == "MANUAL_REVIEW_UNMODELED_GATE"

    def test_removes_all_outgoing_edges(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        old_targets = [e for e in g["edges"]
                       if e.get("frm") == "n_gw" and e.get("to") in ("n_a", "n_b")]
        assert old_targets == []

    def test_exactly_one_edge_to_station(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        out = [e for e in g["edges"] if e.get("frm") == "n_gw"]
        assert len(out) == 1
        assert out[0]["to"] == "n_exc_unmodeled_gate"
        assert out[0]["condition"] is None

    def test_edge_has_patch_meta(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        out = [e for e in g["edges"] if e.get("frm") == "n_gw"]
        assert len(out) == 1
        meta = out[0].get("meta", {})
        assert meta.get("origin") == "normalize"
        assert "patch_id" in meta
        assert "rationale" in meta

    def test_node_has_patch_meta(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"].get("meta", {})
        assert meta.get("origin") == "normalize"
        assert "patch_id" in meta

    def test_idempotent(self):
        g = self._graph_with_unparseable_gateway()
        g, log1 = convert_unparseable_gateways_to_station(g)
        edges_after_1 = len(g["edges"])
        g, log2 = convert_unparseable_gateways_to_station(g)
        edges_after_2 = len(g["edges"])
        assert edges_after_1 == edges_after_2
        # Second run should produce no conversion log entries
        assert not any("[UNPARSE]" in line and "converted" in line for line in log2)

    def test_skips_gateway_with_parseable_conditions(self):
        """A gateway whose conditions all normalise fine is NOT converted."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Station",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # n4 is already a gateway with "MATCH_3_WAY" condition — normalises fine
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n4"]["kind"] == "gateway"  # unchanged

    def test_raises_if_station_missing(self):
        """ValueError if unmodeled gate station does not exist."""
        g = _minimal()
        # Add an unparseable gateway but NO station
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Bad",
            "action": None,
            "decision": {"type": "IF_CONDITION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:IF_CONDITION@n_gw"},
        })
        g["edges"].append({"frm": "n_gw", "to": "n5", "condition": "IF_CONDITION"})
        with pytest.raises(ValueError, match="MANUAL_REVIEW_UNMODELED_GATE"):
            convert_unparseable_gateways_to_station(g)

    def test_skips_known_structured_gateway_with_mixed_conditions(self):
        """A MATCH_3_WAY gateway with some parseable + some unparseable
        conditions is NOT converted — its dedicated pass handles it."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Station",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # Override n4 to have a mix of parseable and unparseable conditions
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n4"]
        g["edges"].extend([
            {"frm": "n4", "to": "n5",  "condition": "MATCH_3_WAY"},       # parseable
            {"frm": "n4", "to": "n32", "condition": "SCHEDULE_PAYMENT"},  # unparseable
        ])
        g, log = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n4"]["kind"] == "gateway"  # NOT converted
        assert any("skipped" in line and "MATCH_3_WAY" in line for line in log)

    def test_converts_unknown_gateway_with_mixed_conditions(self):
        """A gateway with unknown decision type and mixed conditions IS converted."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Station",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # Add a gateway with a non-structured decision type
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Custom Gate",
            "action": None,
            "decision": {"type": "CUSTOM_CHECK", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:CUSTOM_CHECK@n_gw"},
        })
        g["nodes"].append({
            "id": "n_t1", "kind": "task", "name": "Target",
            "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:X@n_t1"},
        })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n5",   "condition": "MATCH_3_WAY"},      # parseable
            {"frm": "n_gw", "to": "n_t1", "condition": "IF_CONDITION"},      # unparseable
        ])
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"  # converted
        assert nmap["n_gw"]["action"]["type"] == "MANUAL_REVIEW_UNMODELED_GATE"

    def test_converts_known_gateway_when_all_conditions_unparseable(self):
        """Even a MATCH_3_WAY gateway is converted if ALL conditions are None."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Station",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # Override n4 so ALL conditions are unparseable
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n4"]
        g["edges"].extend([
            {"frm": "n4", "to": "n5",  "condition": "IF_CONDITION"},
            {"frm": "n4", "to": "n32", "condition": "SCHEDULE_PAYMENT"},
        ])
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n4"]["kind"] == "task"  # converted — no parseable conditions left
        assert nmap["n4"]["action"]["type"] == "MANUAL_REVIEW_UNMODELED_GATE"

    def test_linter_passes_after_conversion(self):
        """After conversion the fixture graph has no E_CONDITION_PARSE."""
        from src.linter import lint_process_graph
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        results = lint_process_graph(g)
        codes = {r.code for r in results}
        assert "E_CONDITION_PARSE" not in codes


# ===========================================================================
# Pass 10 — convert_fanout_gateways_to_ambiguous_station
# ===========================================================================

class TestConvertFanoutGatewaysToAmbiguousStation:

    def _graph_with_fanout_gateway(self) -> dict:
        """Graph with a gateway (n_gw) that has 3 edges all sharing has_po == true."""
        g = _minimal()
        # Add ambiguous-route station
        g["nodes"].append({
            "id": "n_exc_ambiguous_route", "kind": "task",
            "name": "Exception — Ambiguous Route",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {"reason": "AMBIGUOUS_ROUTE"}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE@n_exc_ambiguous_route",
                     "intent_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"},
        })
        # Add fan-out gateway
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "HAS_PO Fan-out",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO@n_gw"},
        })
        # Targets
        for nid in ("n_t1", "n_t2", "n_t3"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {nid}",
                "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:X@{nid}"},
            })
        # 3 edges all with has_po == true (fan-out)
        g["edges"].extend([
            {"frm": "n5",   "to": "n_gw",  "condition": None},
            {"frm": "n_gw", "to": "n_t1",  "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2",  "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t3",  "condition": "has_po == true"},
        ])
        return g

    def test_converts_gateway_to_task(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"
        assert nmap["n_gw"]["action"]["type"] == "MANUAL_REVIEW_AMBIGUOUS_ROUTE"

    def test_removes_all_outgoing_edges(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        old_targets = [e for e in g["edges"]
                       if e.get("frm") == "n_gw" and e.get("to") in ("n_t1", "n_t2", "n_t3")]
        assert old_targets == []

    def test_exactly_one_edge_to_station(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        out = [e for e in g["edges"] if e.get("frm") == "n_gw"]
        assert len(out) == 1
        assert out[0]["to"] == "n_exc_ambiguous_route"
        assert out[0]["condition"] is None

    def test_edge_has_patch_meta(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        out = [e for e in g["edges"] if e.get("frm") == "n_gw"]
        meta = out[0].get("meta", {})
        assert meta.get("origin") == "normalize"
        assert "patch_id" in meta
        assert "rationale" in meta

    def test_node_has_patch_meta(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"].get("meta", {})
        assert meta.get("origin") == "normalize"
        assert "patch_id" in meta

    def test_idempotent(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        edges_after_1 = len(g["edges"])
        g, log2 = convert_fanout_gateways_to_ambiguous_station(g)
        edges_after_2 = len(g["edges"])
        assert edges_after_1 == edges_after_2
        assert not any("[FANOUT]" in line and "converted" in line for line in log2)

    def test_skips_gateway_without_fanout(self):
        """A gateway with distinct conditions on each edge is NOT converted."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_exc_ambiguous_route", "kind": "task",
            "name": "Station",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE@s",
                     "intent_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"},
        })
        # n4 has a single MATCH_3_WAY edge — no fan-out
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n4"]["kind"] == "gateway"

    def test_raises_if_station_missing(self):
        """ValueError if ambiguous-route station does not exist."""
        g = _minimal()
        # Add a fan-out gateway but NO station
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Fan-out",
            "action": None, "decision": None, "evidence": [],
            "meta": {"canonical_key": "gw:X@n_gw"},
        })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n4",  "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n5",  "condition": "has_po == true"},
        ])
        with pytest.raises(ValueError, match="MANUAL_REVIEW_AMBIGUOUS_ROUTE"):
            convert_fanout_gateways_to_ambiguous_station(g)

    def test_linter_passes_after_conversion(self):
        """After conversion the fixture graph has no E_GATEWAY_FANOUT_SAME_CONDITION."""
        from src.linter import lint_process_graph
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        results = lint_process_graph(g)
        codes = {r.code for r in results}
        assert "E_GATEWAY_FANOUT_SAME_CONDITION" not in codes


# ===========================================================================
# Pass 10 — convert_whitelisted_fanout_to_sequential
# ===========================================================================

class TestConvertWhitelistedFanoutToSequential:

    def _graph_with_haspo_fanout(self) -> dict:
        """Graph with a whitelisted HAS_PO gateway that has 3 fan-out edges."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "HAS_PO Fan-out",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO", "intent_key": "gw:HAS_PO"},
        })
        # Targets with distinct action.types for priority sorting
        for nid, atype in [("n_t1", "ROUTE_FOR_REVIEW"), ("n_t2", "REVIEW"), ("n_t3", "UPDATE_RECORD")]:
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {atype}",
                "action": {"type": atype, "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:{atype}@{nid}"},
            })
        # 3 edges all with has_po == true (fan-out)
        g["edges"].extend([
            {"frm": "n5",   "to": "n_gw",  "condition": None},
            {"frm": "n_gw", "to": "n_t1",  "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2",  "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t3",  "condition": "has_po == true"},
        ])
        return g

    def test_converts_gateway_to_sequential_dispatch_task(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"
        assert nmap["n_gw"]["action"]["type"] == "SEQUENTIAL_DISPATCH"

    def test_chain_stored_in_extra(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        extra = nmap["n_gw"]["action"]["extra"]
        assert extra["chain"] == ["n_t1", "n_t2", "n_t3"]
        assert extra["dispatch_condition"] == "has_po == true"

    def test_chain_order_follows_priority(self):
        """Targets are sorted by action.type priority, then node id."""
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        # ROUTE_FOR_REVIEW(10) < REVIEW(20) < UPDATE_RECORD(30)
        assert nmap["n_gw"]["action"]["extra"]["chain"] == ["n_t1", "n_t2", "n_t3"]

    def test_removes_fanout_edges(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        cond_edges = [e for e in g["edges"]
                      if e.get("frm") == "n_gw" and e.get("condition") is not None]
        assert cond_edges == []

    def test_unconditional_chain_edges_created(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        # Chain: n_gw -> n_t1 -> n_t2 -> n_t3
        chain_pairs = [("n_gw", "n_t1"), ("n_t1", "n_t2"), ("n_t2", "n_t3")]
        for frm, to in chain_pairs:
            edges = [e for e in g["edges"] if e.get("frm") == frm and e.get("to") == to]
            assert len(edges) == 1, f"Missing chain edge {frm} -> {to}"
            assert edges[0]["condition"] is None

    def test_removes_inter_target_edges(self):
        """Existing edges between targets in the chain are removed."""
        g = self._graph_with_haspo_fanout()
        # Add pre-existing inter-target edge (miner noise)
        g["edges"].append({"frm": "n_t1", "to": "n_t2", "condition": "has_po == true"})
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        # The conditional inter-target edge should be removed
        cond_inter = [e for e in g["edges"]
                      if e.get("frm") == "n_t1" and e.get("to") == "n_t2"
                      and e.get("condition") is not None]
        assert cond_inter == []

    def test_skips_non_whitelisted_gateway(self):
        """A gateway NOT in the whitelist is untouched."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Custom",
            "action": None,
            "decision": {"type": "CUSTOM_CHECK", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:CUSTOM_CHECK"},
        })
        for nid in ("n_t1", "n_t2", "n_t3"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {nid}",
                "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:X@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n_t1", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t3", "condition": "has_po == true"},
        ])
        g, log = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "gateway"

    def test_skips_when_targets_include_gateway(self):
        """If any target is a gateway, skip conversion."""
        g = self._graph_with_haspo_fanout()
        nmap = {n["id"]: n for n in g["nodes"]}
        nmap["n_t2"]["kind"] = "gateway"
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        assert nmap["n_gw"]["kind"] == "gateway"

    def test_skips_when_fewer_than_3_fanout_edges(self):
        """Only convert when 3+ edges share the same condition."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "HAS_PO",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO", "intent_key": "gw:HAS_PO"},
        })
        for nid in ("n_t1", "n_t2"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {nid}",
                "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:X@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n_t1", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2", "condition": "has_po == true"},
        ])
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "gateway"

    def test_idempotent(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        edges_after_1 = [(e.get("frm"), e.get("to"), e.get("condition")) for e in g["edges"]]
        g, log2 = convert_whitelisted_fanout_to_sequential(g)
        edges_after_2 = [(e.get("frm"), e.get("to"), e.get("condition")) for e in g["edges"]]
        assert sorted(edges_after_1) == sorted(edges_after_2)
        assert not any("[SEQ]" in line and "converting" in line for line in log2)

    def test_node_has_patch_meta(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"].get("meta", {})
        assert meta.get("origin") == "normalize"
        assert meta.get("patch_id") == "normalize_sequential_dispatch"
        assert meta.get("synthetic") is True
        assert "fan-out" in meta.get("rationale", "")
        assert "action.type priority" in meta.get("rationale", "")

    def test_approve_or_reject_also_converted(self):
        """APPROVE_OR_REJECT intent_key is also in the whitelist."""
        g = _minimal()
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Approve or Reject",
            "action": None,
            "decision": {"type": "APPROVE_OR_REJECT", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:APPROVE_OR_REJECT", "intent_key": "gw:APPROVE_OR_REJECT"},
        })
        for nid, atype in [("n_t1", "SCHEDULE_PAYMENT"), ("n_t2", "NOTIFY"), ("n_t3", "UPDATE_STATUS")]:
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {atype}",
                "action": {"type": atype, "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:{atype}@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n_t1", "condition": "amount <= 5000"},
            {"frm": "n_gw", "to": "n_t2", "condition": "amount <= 5000"},
            {"frm": "n_gw", "to": "n_t3", "condition": "amount <= 5000"},
        ])
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"
        assert nmap["n_gw"]["action"]["type"] == "SEQUENTIAL_DISPATCH"
        # Priority order: SCHEDULE_PAYMENT(50) < NOTIFY(70) < UPDATE_STATUS(80)
        assert nmap["n_gw"]["action"]["extra"]["chain"] == ["n_t1", "n_t2", "n_t3"]


# ===========================================================================
# Pass 14 — deduplicate_edges
# ===========================================================================

class TestDeduplicateEdges:

    def test_removes_exact_duplicates(self):
        g = _minimal()
        # Add duplicate edge
        g["edges"].append({"frm": "n1", "to": "n3", "condition": None})
        g, log = deduplicate_edges(g)
        n1_edges = [e for e in g["edges"] if e.get("frm") == "n1"]
        assert len(n1_edges) == 1

    def test_keeps_different_conditions(self):
        g = _minimal()
        g["edges"].append({"frm": "n4", "to": "n5", "condition": "match_3_way == false"})
        before = len(g["edges"])
        g, _ = deduplicate_edges(g)
        assert len(g["edges"]) == before  # no duplicates, none removed

    def test_log_entries_for_removed_edges(self):
        g = _minimal()
        g["edges"].append({"frm": "n1", "to": "n3", "condition": None})
        _, log = deduplicate_edges(g)
        assert any("DEDUP" in line for line in log)

    def test_idempotent(self):
        g = _minimal()
        g["edges"].append({"frm": "n1", "to": "n3", "condition": None})
        g, _ = deduplicate_edges(g)
        count_1 = len(g["edges"])
        g, _ = deduplicate_edges(g)
        count_2 = len(g["edges"])
        assert count_1 == count_2


# ===========================================================================
# normalize_all orchestrator
# ===========================================================================

class TestNormalizeAll:

    def test_returns_data_and_log(self):
        g = _minimal()
        result, log = normalize_all(g)
        assert isinstance(result, dict)
        assert isinstance(log, list)

    def test_log_is_not_empty_on_dirty_graph(self):
        g = _minimal()
        _, log = normalize_all(g)
        # At minimum art_account_code is injected, exception nodes are injected
        assert len(log) > 0

    def test_all_passes_run(self):
        g = _minimal()
        _, log = normalize_all(g)
        all_log = "\n".join(log)
        assert "fix_artifact_references" in all_log
        assert "inject_exception_nodes"  in all_log

    def test_idempotent(self):
        """Running normalize_all twice yields the same graph."""
        g = _minimal()
        g1, _ = normalize_all(copy.deepcopy(g))
        g2, _ = normalize_all(copy.deepcopy(g1))

        # Compare nodes by id->kind
        nodes_1 = {n["id"]: n["kind"] for n in g1["nodes"]}
        nodes_2 = {n["id"]: n["kind"] for n in g2["nodes"]}
        assert nodes_1 == nodes_2

        # Compare edge set
        edges_1 = sorted((e.get("frm"), e.get("to"), e.get("condition")) for e in g1["edges"])
        edges_2 = sorted((e.get("frm"), e.get("to"), e.get("condition")) for e in g2["edges"])
        assert edges_1 == edges_2

    def test_exception_nodes_present_after_normalize_all(self):
        g = _minimal()
        g, _ = normalize_all(g)
        ids = {n["id"] for n in g["nodes"]}
        assert "n_no_match" in ids
        assert "n_manual_review_gate" in ids

    def test_art_account_code_present_after_normalize_all(self):
        g = _minimal()
        g, _ = normalize_all(g)
        ids = {a["id"] for a in g["artifacts"]}
        assert "art_account_code" in ids


# ===========================================================================
# Pass 9 — wire_bad_extraction_route
# ===========================================================================

def _graph_with_enter_record() -> dict:
    """Graph with ENTER_RECORD, VALIDATE_FIELDS, and REJECT_INVOICE nodes."""
    return {
        "actors": [
            {"id": "role_ap_clerk", "type": "human_role", "name": "AP Clerk"},
        ],
        "artifacts": [
            {"id": "art_invoice", "type": "document", "name": "Invoice"},
        ],
        "nodes": [
            {
                "id": "n1", "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            {
                "id": "n2", "kind": "task", "name": "Enter Record",
                "action": {
                    "type": "ENTER_RECORD", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:ENTER_RECORD"},
            },
            {
                "id": "n3", "kind": "task", "name": "Validate Fields",
                "action": {
                    "type": "VALIDATE_FIELDS", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:VALIDATE_FIELDS"},
            },
            {
                "id": "n_reject", "kind": "task", "name": "Reject Invoice",
                "action": {
                    "type": "REJECT_INVOICE", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:REJECT_INVOICE"},
            },
            {
                "id": "n32", "kind": "end", "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
        ],
        "edges": [
            {"frm": "n1", "to": "n2", "condition": None},
            {"frm": "n2", "to": "n3", "condition": None},
            {"frm": "n3", "to": "n32", "condition": None},
            {"frm": "n_reject", "to": "n32", "condition": None},
        ],
    }


class TestWireBadExtractionRoute:

    def test_injects_conditional_edge(self):
        g = _graph_with_enter_record()
        g, log = wire_bad_extraction_route(g)
        cond_edges = [
            e for e in g["edges"]
            if e.get("frm") == "n2" and e.get("condition") == 'status == "BAD_EXTRACTION"'
        ]
        assert len(cond_edges) == 1
        assert cond_edges[0]["to"] == "n_reject"

    def test_conditional_edge_before_unconditional(self):
        g = _graph_with_enter_record()
        g, _ = wire_bad_extraction_route(g)
        n2_edges = [(i, e) for i, e in enumerate(g["edges"]) if e.get("frm") == "n2"]
        cond_idx = next(i for i, e in n2_edges if e.get("condition") is not None)
        uncond_idx = next(i for i, e in n2_edges if e.get("condition") is None)
        assert cond_idx < uncond_idx

    def test_idempotent(self):
        g = _graph_with_enter_record()
        g, _ = wire_bad_extraction_route(g)
        edges_1 = len(g["edges"])
        g, _ = wire_bad_extraction_route(g)
        edges_2 = len(g["edges"])
        assert edges_1 == edges_2

    def test_noop_when_no_enter_record(self):
        g = _minimal()
        g, log = wire_bad_extraction_route(g)
        assert any("No ENTER_RECORD" in line for line in log)

    def test_noop_when_no_reject_node(self):
        g = _graph_with_enter_record()
        # Remove the reject node
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n_reject"]
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n_reject"]
        g, log = wire_bad_extraction_route(g)
        assert any("No rejection node" in line for line in log)


# ===========================================================================
# Real-router integration: BAD_EXTRACTION conditional beats unconditional
# ===========================================================================

class TestBadExtractionRouterIntegration:
    """
    End-to-end test using the REAL router to confirm that
    status == "BAD_EXTRACTION" routes to the rejection node,
    not the unconditional VALIDATE_FIELDS fallback.

    No mocking of get_predicate or predicate evaluation.
    """

    def test_bad_extraction_routes_to_reject(self):
        g = _graph_with_enter_record()
        g, _ = wire_bad_extraction_route(g)

        # The outgoing edges from n2
        n2_edges = [e for e in g["edges"] if e.get("frm") == "n2"]
        n2_node = next(n for n in g["nodes"] if n["id"] == "n2")

        # Simulate state with BAD_EXTRACTION
        state = {
            "invoice_id": "TEST",
            "vendor": "",
            "amount": 0.0,
            "has_po": False,
            "po_match": False,
            "match_3_way": False,
            "status": "BAD_EXTRACTION",
            "current_node": "n2",
            "audit_log": [],
            "raw_text": "",
            "extraction": {},
            "provenance": {},
        }

        # Call the real router
        next_node = route_edge(state, n2_edges, n2_node)
        assert next_node == "n_reject"

    def test_normal_status_routes_to_validate(self):
        g = _graph_with_enter_record()
        g, _ = wire_bad_extraction_route(g)

        n2_edges = [e for e in g["edges"] if e.get("frm") == "n2"]
        n2_node = next(n for n in g["nodes"] if n["id"] == "n2")

        # Simulate state with DATA_EXTRACTED (normal path)
        state = {
            "invoice_id": "TEST",
            "vendor": "Acme",
            "amount": 100.0,
            "has_po": True,
            "po_match": True,
            "match_3_way": True,
            "status": "DATA_EXTRACTED",
            "current_node": "n2",
            "audit_log": [],
            "raw_text": "",
            "extraction": {},
            "provenance": {},
        }

        next_node = route_edge(state, n2_edges, n2_node)
        assert next_node == "n3"


# ===========================================================================
# Contract postcondition tests — one per pass, tested in isolation
# ===========================================================================

class TestContractPass1:
    """Pass 1 postcondition: art_account_code in artifacts."""

    def test_contract_art_account_code_present(self):
        g = _minimal()
        g, _ = fix_artifact_references(g)
        art_ids = {a["id"] for a in g["artifacts"]}
        assert "art_account_code" in art_ids


class TestContractPass2:
    """Pass 2 postcondition: all canonical_key values unique."""

    def test_contract_canonical_keys_unique(self):
        g = _minimal()
        # Add duplicate canonical_key to trigger the pass
        g["nodes"].append({
            "id": "n22", "kind": "task", "name": "Approve copy",
            "action": {"type": "APPROVE", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:APPROVE"},
        })
        g, _ = fix_canonical_key_duplicates(g)
        ckeys = [
            n["meta"]["canonical_key"] for n in g["nodes"]
            if (n.get("meta") or {}).get("canonical_key")
        ]
        assert len(ckeys) == len(set(ckeys))


class TestContractPass3:
    """Pass 3 postcondition: no known synonym string in edge conditions."""

    def test_contract_no_synonym_conditions(self):
        g = _minimal()
        g, _ = normalize_edge_conditions(g)
        for e in g["edges"]:
            cond = e.get("condition")
            if cond is None:
                continue
            # Known synonyms that should have been replaced
            assert cond != "MATCH_3_WAY"
            assert cond != "HAS_PO"


class TestContractPass4:
    """Pass 4 postcondition: n_no_match and n_manual_review_gate in nodes."""

    def test_contract_exception_nodes_exist(self):
        g = _minimal()
        g, _ = inject_exception_nodes(g)
        ids = {n["id"] for n in g["nodes"]}
        assert "n_no_match" in ids
        assert "n_manual_review_gate" in ids


class TestContractPass5:
    """Pass 5 postcondition: n4 outgoing edges correct (or no-op if not MATCH_3_WAY)."""

    def test_contract_n4_two_exclusive_branches(self):
        g = _minimal()
        # Inject prereqs: exception stations + n_threshold
        g, _ = inject_exception_nodes(g)
        g["nodes"].append({
            "id": "n_threshold", "kind": "gateway", "name": "Threshold",
            "action": None,
            "decision": {"type": "THRESHOLD_AMOUNT_10K", "inputs": [], "expression": None},
            "evidence": [], "meta": {"canonical_key": "gw:THRESHOLD_AMOUNT_10K"},
        })
        # Add fan-out to trigger the pass
        g["edges"].extend([
            {"frm": "n4", "to": "n_threshold", "condition": "MATCH_3_WAY"},
            {"frm": "n4", "to": "n5",          "condition": "MATCH_3_WAY"},
        ])
        g, _ = fix_match3way_gateway(g)
        out = [e for e in g["edges"] if e.get("frm") == "n4"]
        assert len(out) == 2
        conds = {e["condition"] for e in out}
        assert conds == {'match_result == "MATCH"', 'match_result == "NO_MATCH"'}


class TestContractPass5b:
    """Pass 5b postcondition: {gw_id}_decision has 3 canonical branches."""

    def _stations(self) -> list[dict]:
        return [
            {
                "id": "n_no_match", "kind": "task",
                "name": "Manual Review — Match Failed",
                "action": {"type": "MANUAL_REVIEW_MATCH_FAILED",
                           "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_MATCH_FAILED@n_no_match",
                         "intent_key": "task:MANUAL_REVIEW_MATCH_FAILED"},
            },
            {
                "id": "n_manual_review_gate", "kind": "task",
                "name": "Manual Review — Unmodeled Gate",
                "action": {"type": "MANUAL_REVIEW_UNMODELED_GATE",
                           "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_manual_review_gate",
                         "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
            },
        ]

    def test_contract_decision_gateway_has_three_branches(self):
        g = _minimal()
        # Replace n5 with a secondary MATCH_3_WAY gateway
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "n5"]
        g["nodes"].extend([
            {
                "id": "n5", "kind": "gateway", "name": "Decision",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY@n5",
                         "intent_key": "gw:MATCH_3_WAY"},
            },
            {
                "id": "n6", "kind": "task", "name": "Approve",
                "action": {"type": "APPROVE", "actor_id": "role_director",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE@n6"},
            },
            {
                "id": "n7", "kind": "task", "name": "Schedule Payment",
                "action": {"type": "SCHEDULE_PAYMENT", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:SCHEDULE_PAYMENT@n7"},
            },
            {
                "id": "n8", "kind": "task", "name": "Execute Payment",
                "action": {"type": "EXECUTE_PAYMENT", "actor_id": "sys_erp",
                           "artifact_id": "art_payment", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:EXECUTE_PAYMENT@n8"},
            },
            *self._stations(),
        ])
        g["edges"] = [e for e in g["edges"] if e.get("frm") != "n5"]
        g["edges"].extend([
            {"frm": "n5", "to": "n6", "condition": "MATCH_3_WAY"},
            {"frm": "n5", "to": "n7", "condition": "MATCH_3_WAY"},
        ])
        g, _ = fix_secondary_match_gateways(g)
        out_dec = [e for e in g["edges"] if e.get("frm") == "n5_decision"]
        assert len(out_dec) == 3
        conds = {e["condition"] for e in out_dec}
        assert conds == {
            'match_result == "MATCH"',
            'match_result == "NO_MATCH"',
            'match_result == "UNKNOWN"',
        }


class TestContractPass6:
    """Pass 6 postcondition: no edge n7→n8."""

    def test_contract_no_n7_to_n8_edge(self):
        g = _graph_with_n7_to_n8()
        g, _ = fix_main_execution_path(g)
        bad = [e for e in g["edges"]
               if e.get("frm") == "n7" and e.get("to") == "n8"]
        assert bad == []


class TestContractPass7:
    """Pass 7 postcondition: n8 has 2 exclusive branches."""

    def test_contract_n8_two_exclusive_branches(self):
        g = _graph_with_n8_fanout()
        g, _ = fix_haspo_gateway(g)
        out = [e for e in g["edges"] if e.get("frm") == "n8"]
        assert len(out) == 2
        conds = {e["condition"] for e in out}
        assert conds == {"has_po == true", "has_po == false"}


class TestContractPass8:
    """Pass 8 postcondition: n28 has status=="DUPLICATE" / status!="DUPLICATE"."""

    def test_contract_n28_explicit_duplicate_conditions(self):
        g = _minimal()
        # Add station for n16 exception conversion
        g["nodes"].append({
            "id": "n_manual_review_gate", "kind": "task",
            "name": "Manual Review Gate",
            "action": {"type": "MANUAL_REVIEW_UNMODELED_GATE",
                       "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice", "extra": {}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_manual_review_gate",
                     "origin": "normalize"},
        })
        # Add n28 gateway with placeholder conditions
        for nid in ("n28", "n29", "n30", "n31"):
            g["nodes"].append({
                "id": nid,
                "kind": "gateway" if nid == "n28" else "task",
                "name": f"Node {nid}",
                "action": None if nid == "n28" else {
                    "type": "TASK_X", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": ({"type": "IF_CONDITION", "inputs": [], "expression": None}
                             if nid == "n28" else None),
                "evidence": [],
                "meta": {"canonical_key": f"gw:duplicate@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n28", "to": "n29", "condition": "IF_CONDITION"},
            {"frm": "n28", "to": "n30", "condition": "IF_CONDITION"},
        ])
        g, _ = fix_placeholder_gateways(g)
        out = [e for e in g["edges"] if e.get("frm") == "n28"]
        conds = {e.get("condition") for e in out}
        assert 'status == "DUPLICATE"' in conds
        assert 'status != "DUPLICATE"' in conds


class TestContractPass9:
    """Pass 9 postcondition: no all-unparseable gateways remain."""

    def test_contract_no_unparseable_gateways(self):
        g = _minimal()
        # Add station (prerequisite)
        g["nodes"].append({
            "id": "n_exc_unmodeled_gate", "kind": "task",
            "name": "Exception — Unmodeled Gate",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice",
                       "extra": {"reason": "UNMODELED_GATE"}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_exc_unmodeled_gate",
                     "intent_key": "task:MANUAL_REVIEW_UNMODELED_GATE"},
        })
        # Add unparseable gateway
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Unknown Decision",
            "action": None,
            "decision": {"type": "IF_CONDITION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:IF_CONDITION@n_gw"},
        })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n5", "condition": "IF_CONDITION"},
            {"frm": "n_gw", "to": "n32", "condition": "IF_CONDITION"},
        ])
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"


class TestContractPass10:
    """Pass 10 postcondition: converted node is SEQUENTIAL_DISPATCH with chain."""

    def test_contract_sequential_dispatch_with_chain(self):
        g = _minimal()
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "HAS_PO Fan-out",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO", "intent_key": "gw:HAS_PO"},
        })
        for nid, atype in [("n_t1", "ROUTE_FOR_REVIEW"),
                           ("n_t2", "REVIEW"),
                           ("n_t3", "UPDATE_RECORD")]:
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {atype}",
                "action": {"type": atype, "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:{atype}@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n_t1", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t3", "condition": "has_po == true"},
        ])
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["action"]["type"] == "SEQUENTIAL_DISPATCH"
        assert "chain" in nmap["n_gw"]["action"]["extra"]


class TestContractPass11:
    """Pass 11 postcondition: no gateway has fan-out edges."""

    def test_contract_no_fanout_gateways(self):
        g = _minimal()
        # Add ambiguous-route station
        g["nodes"].append({
            "id": "n_exc_ambiguous_route", "kind": "task",
            "name": "Exception — Ambiguous Route",
            "action": {"type": "ROUTE_FOR_REVIEW", "actor_id": "role_ap_clerk",
                       "artifact_id": "art_invoice",
                       "extra": {"reason": "AMBIGUOUS_ROUTE"}},
            "decision": None, "evidence": [],
            "meta": {"canonical_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE@n_exc_ambiguous_route",
                     "intent_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"},
        })
        # Add fan-out gateway
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Fan-out",
            "action": None,
            "decision": {"type": "HAS_PO", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:HAS_PO@n_gw"},
        })
        for nid in ("n_t1", "n_t2"):
            g["nodes"].append({
                "id": nid, "kind": "task", "name": f"Task {nid}",
                "action": {"type": "TASK_X", "actor_id": "role_ap_clerk",
                           "artifact_id": "art_invoice", "extra": {}},
                "decision": None, "evidence": [],
                "meta": {"canonical_key": f"task:X@{nid}"},
            })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n_t1", "condition": "has_po == true"},
            {"frm": "n_gw", "to": "n_t2", "condition": "has_po == true"},
        ])
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        assert nmap["n_gw"]["kind"] == "task"


class TestContractPass12:
    """Pass 12 postcondition: ENTER_RECORD→rejection edge with status=="BAD_EXTRACTION"."""

    def test_contract_bad_extraction_edge_exists(self):
        g = _graph_with_enter_record()
        g, _ = wire_bad_extraction_route(g)
        cond_edges = [
            e for e in g["edges"]
            if e.get("frm") == "n2"
            and e.get("condition") == 'status == "BAD_EXTRACTION"'
        ]
        assert len(cond_edges) == 1
        assert cond_edges[0]["to"] == "n_reject"


class TestContractPass13:
    """Pass 13 postcondition: every match_result gateway has UNKNOWN edge."""

    def test_contract_unknown_guardrail_injected(self):
        g = _minimal()
        # Run pass 4 to get exception stations
        g, _ = inject_exception_nodes(g)
        # Create a gateway with match_result edges but no UNKNOWN
        g["nodes"].append({
            "id": "n_gw", "kind": "gateway", "name": "Match Decision",
            "action": None,
            "decision": {"type": "MATCH_DECISION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {"canonical_key": "gw:MATCH_DECISION@n_gw",
                     "intent_key": "gw:MATCH_DECISION"},
        })
        g["edges"].extend([
            {"frm": "n_gw", "to": "n5", "condition": 'match_result == "MATCH"'},
            {"frm": "n_gw", "to": "n_no_match",
             "condition": 'match_result == "NO_MATCH"'},
        ])
        g, _ = inject_match_result_unknown_guardrail(g)
        unknown_edges = [
            e for e in g["edges"]
            if e.get("frm") == "n_gw"
            and e.get("condition") == 'match_result == "UNKNOWN"'
        ]
        assert len(unknown_edges) == 1


class TestContractPass14:
    """Pass 14 postcondition: no duplicate (frm, to, condition) triples."""

    def test_contract_no_duplicate_edges(self):
        g = _minimal()
        # Add duplicate edge
        g["edges"].append({"frm": "n1", "to": "n3", "condition": None})
        g, _ = deduplicate_edges(g)
        triples = [
            (e.get("frm"), e.get("to"), e.get("condition"))
            for e in g["edges"]
        ]
        assert len(triples) == len(set(triples))


class TestContractPass15:
    """Pass 15 postcondition: no duplicate (frm, to, condition) triples (strict)."""

    def test_contract_no_duplicate_edges_strict(self):
        g = _minimal()
        # Add duplicate edge
        g["edges"].append({"frm": "n1", "to": "n3", "condition": None})
        g, _ = deduplicate_edges_strict(g)
        triples = [
            (e.get("frm"), e.get("to"), e.get("condition"))
            for e in g["edges"]
        ]
        assert len(triples) == len(set(triples))


# ===========================================================================
# Synthetic metadata tests — verify passes write correct synthetic fields
# ===========================================================================

class TestSyntheticMetadataPass5b(TestFixSecondaryMatchGateways):
    """Pass 5b: decision node has synthetic + assumption + origin_pass."""

    def test_decision_node_synthetic_metadata(self):
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n5_decision"]["meta"]
        assert meta.get("synthetic") is True
        assert meta["semantic_assumption"] == "match_3way_task_decision_split"
        assert meta["origin_pass"] == "fix_secondary_match_gateways"

    def test_task_node_synthetic_metadata(self):
        g = self._graph_with_n5_noise()
        g, _ = fix_secondary_match_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n5"]["meta"]
        assert meta.get("synthetic") is True
        assert meta["semantic_assumption"] == "match_3way_task_decision_split"
        assert meta["origin_pass"] == "fix_secondary_match_gateways"


class TestSyntheticMetadataPass8(TestFixPlaceholderGateways):
    """Pass 8 (n28): node has synthetic_edges list with correct entries."""

    def test_n28_synthetic_edges(self):
        g = self._graph_with_n16_n28()
        g, _ = fix_placeholder_gateways(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        se = nmap["n28"]["meta"].get("synthetic_edges", [])
        assert len(se) == 2
        assumptions = {e["semantic_assumption"] for e in se}
        assert assumptions == {"duplicate_check_derivable"}
        for entry in se:
            assert entry["origin_pass"] == "fix_placeholder_gateways"
            assert "to" in entry
            assert "condition" in entry


class TestSyntheticMetadataPass9(TestConvertUnparseableGatewaysToStation):
    """Pass 9: converted node has synthetic + assumption + origin_pass."""

    def test_converted_node_synthetic_metadata(self):
        g = self._graph_with_unparseable_gateway()
        g, _ = convert_unparseable_gateways_to_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"]["meta"]
        assert meta.get("synthetic") is True
        assert meta["semantic_assumption"] == "fail_closed_unmodeled"
        assert meta["origin_pass"] == "convert_unparseable_gateways_to_station"


class TestSyntheticMetadataPass10(TestConvertWhitelistedFanoutToSequential):
    """Pass 10: converted node has synthetic + assumption + origin_pass."""

    def test_converted_node_synthetic_metadata(self):
        g = self._graph_with_haspo_fanout()
        g, _ = convert_whitelisted_fanout_to_sequential(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"]["meta"]
        assert meta.get("synthetic") is True
        assert meta["semantic_assumption"] == "do_all_sequential"
        assert meta["origin_pass"] == "convert_whitelisted_fanout_to_sequential"


class TestSyntheticMetadataPass11(TestConvertFanoutGatewaysToAmbiguousStation):
    """Pass 11: converted node has synthetic + assumption + origin_pass."""

    def test_converted_node_synthetic_metadata(self):
        g = self._graph_with_fanout_gateway()
        g, _ = convert_fanout_gateways_to_ambiguous_station(g)
        nmap = {n["id"]: n for n in g["nodes"]}
        meta = nmap["n_gw"]["meta"]
        assert meta.get("synthetic") is True
        assert meta["semantic_assumption"] == "fail_closed_ambiguous"
        assert meta["origin_pass"] == "convert_fanout_gateways_to_ambiguous_station"
