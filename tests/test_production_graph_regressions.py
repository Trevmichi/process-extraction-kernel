"""
tests/test_production_graph_regressions.py
Golden regression tests for the production patched graph.

Loads ``outputs/ap_master_manual_auto_patched.json`` and asserts structural
invariants that must hold after patching + normalisation.  These tests catch
regressions in pass ordering, node injection, and gateway wiring.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.conditions import normalize_condition
from src.linter import lint_process_graph

# ---------------------------------------------------------------------------
# Fixture — load the production patched graph once per session
# ---------------------------------------------------------------------------

PATCHED_PATH = Path(__file__).parent.parent / "outputs" / "ap_master_manual_auto_patched.json"


@pytest.fixture(scope="module")
def graph() -> dict:
    if not PATCHED_PATH.exists():
        pytest.skip("Patched graph not found — run patch_logic.py first")
    return json.loads(PATCHED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nodes_map(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph["nodes"]}


# ===========================================================================
# Lint health
# ===========================================================================

class TestLintHealth:

    def test_zero_lint_errors(self, graph: dict):
        errors = [e for e in lint_process_graph(graph) if e.severity == "error"]
        assert errors == [], (
            "Lint errors:\n" + "\n".join(str(e) for e in errors)
        )

    def test_zero_lint_warnings(self, graph: dict):
        warnings = [e for e in lint_process_graph(graph) if e.severity == "warning"]
        assert warnings == [], (
            "Lint warnings:\n" + "\n".join(str(w) for w in warnings)
        )


# ===========================================================================
# Graph shape
# ===========================================================================

class TestGraphShape:

    def test_node_count(self, graph: dict):
        assert len(graph["nodes"]) == 45

    def test_edge_count(self, graph: dict):
        assert len(graph["edges"]) == 39

    def test_gateway_count(self, graph: dict):
        gateways = [n for n in graph["nodes"] if n["kind"] == "gateway"]
        assert len(gateways) == 2

    def test_gateway_ids(self, graph: dict):
        gw_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "gateway"}
        assert gw_ids == {"n_threshold", "n5_decision"}

    def test_gateway_decision_types(self, nodes_map: dict):
        assert nodes_map["n_threshold"]["decision"]["type"] == "THRESHOLD_AMOUNT_10K"
        assert nodes_map["n5_decision"]["decision"]["type"] == "MATCH_DECISION"


# ===========================================================================
# Match task + decision split
# ===========================================================================

class TestMatchSplit:

    def test_exactly_one_match_decision_gateway(self, graph: dict):
        match_dec = [
            n for n in graph["nodes"]
            if n["kind"] == "gateway"
            and (n.get("decision") or {}).get("type") == "MATCH_DECISION"
        ]
        assert len(match_dec) == 1
        assert match_dec[0]["id"] == "n5_decision"

    def test_match_task_exists(self, nodes_map: dict):
        n5 = nodes_map["n5"]
        assert n5["kind"] == "task"
        assert n5["action"]["type"] == "MATCH_3_WAY"
        meta = n5.get("meta") or {}
        assert "gw:MATCH_3_WAY" in (meta.get("intent_key") or "")

    def test_n4_is_validate_fields_not_gateway(self, nodes_map: dict, graph: dict):
        """n4 is VALIDATE_FIELDS (task) with unconditional edge to n_threshold.

        Regression guard: pass 5 previously treated n4 as a MATCH_3_WAY gateway,
        adding match_result conditions before n5 had set match_result.
        """
        n4 = nodes_map["n4"]
        assert n4["kind"] == "task"
        assert n4["action"]["type"] == "VALIDATE_FIELDS"
        # n4 must have exactly one outgoing edge: unconditional to n_threshold
        n4_edges = [e for e in graph["edges"] if e.get("frm") == "n4"]
        assert len(n4_edges) == 1
        assert n4_edges[0]["to"] == "n_threshold"
        assert n4_edges[0]["condition"] is None

    def test_match_result_set_before_decision(self, graph: dict):
        """n5 (MATCH_3_WAY task) must sit between n_threshold and n5_decision.

        This ensures match_result is set by n5 before n5_decision routes on it.
        """
        # n_threshold -> n5 edge exists
        thresh_to_n5 = [e for e in graph["edges"]
                        if e.get("frm") == "n_threshold" and e.get("to") == "n5"]
        assert len(thresh_to_n5) == 1

        # n5 -> n5_decision (unconditional)
        n5_to_dec = [e for e in graph["edges"]
                     if e.get("frm") == "n5" and e.get("to") == "n5_decision"]
        assert len(n5_to_dec) == 1
        assert n5_to_dec[0]["condition"] is None

    def test_one_match_decision_per_intent_key(self, graph: dict):
        """Each gw:MATCH_3_WAY intent_key has exactly 1 decision gateway."""
        match_intents = set()
        for n in graph["nodes"]:
            meta = n.get("meta") or {}
            ik = meta.get("intent_key") or ""
            ck = meta.get("canonical_key") or ""
            if "gw:MATCH_3_WAY" in ik or "gw:MATCH_3_WAY" in ck:
                if n["id"] != "n4":
                    match_intents.add(n["id"])
        # Each should have exactly one _decision node
        for nid in match_intents:
            dec_id = f"{nid}_decision"
            dec_nodes = [n for n in graph["nodes"] if n["id"] == dec_id]
            assert len(dec_nodes) == 1, f"Expected 1 decision node for {nid}, got {len(dec_nodes)}"


# ===========================================================================
# Exception station counts (by action.type)
# ===========================================================================

class TestExceptionStations:

    def test_station_counts_by_action_type(self, graph: dict):
        counts: Counter[str] = Counter()
        for n in graph["nodes"]:
            atype = (n.get("action") or {}).get("type", "")
            if "MANUAL_REVIEW" in atype or atype == "ROUTE_FOR_REVIEW":
                counts[atype] += 1

        assert counts["MANUAL_REVIEW_MATCH_FAILED"] == 1
        assert counts["MANUAL_REVIEW_UNMODELED_GATE"] == 5
        assert counts["MANUAL_REVIEW_NO_PO"] == 1
        assert counts["ROUTE_FOR_REVIEW"] == 6
        assert counts.get("MANUAL_REVIEW_AMBIGUOUS_ROUTE", 0) == 0


# ===========================================================================
# Sequential dispatch chains
# ===========================================================================

class TestSequentialDispatch:

    def test_sequential_dispatch_count(self, graph: dict):
        seq_nodes = [
            n for n in graph["nodes"]
            if (n.get("action") or {}).get("type") == "SEQUENTIAL_DISPATCH"
        ]
        assert len(seq_nodes) == 2

    def test_n9_is_sequential_dispatch(self, nodes_map: dict):
        n9 = nodes_map["n9"]
        assert n9["kind"] == "task"
        assert n9["action"]["type"] == "SEQUENTIAL_DISPATCH"
        assert n9["action"]["extra"]["chain"] == ["n10", "n11", "n12"]

    def test_n13_is_sequential_dispatch(self, nodes_map: dict):
        n13 = nodes_map["n13"]
        assert n13["kind"] == "task"
        assert n13["action"]["type"] == "SEQUENTIAL_DISPATCH"
        assert n13["action"]["extra"]["chain"] == ["n14", "n15", "n16"]

    def test_n9_chain_edges(self, graph: dict):
        """n9 → n10 → n11 → n12 all unconditional."""
        for frm, to in [("n9", "n10"), ("n10", "n11"), ("n11", "n12")]:
            edges = [e for e in graph["edges"]
                     if e.get("frm") == frm and e.get("to") == to]
            assert len(edges) == 1, f"Missing chain edge {frm} -> {to}"
            assert edges[0]["condition"] is None

    def test_n13_chain_edges(self, graph: dict):
        """n13 → n14 → n15 → n16 all unconditional."""
        for frm, to in [("n13", "n14"), ("n14", "n15"), ("n15", "n16")]:
            edges = [e for e in graph["edges"]
                     if e.get("frm") == frm and e.get("to") == to]
            assert len(edges) == 1, f"Missing chain edge {frm} -> {to}"
            assert edges[0]["condition"] is None


# ===========================================================================
# No gateway fan-out with same normalized condition
# ===========================================================================

class TestNoGatewayFanout:

    def test_no_fanout_same_condition(self, graph: dict):
        """No gateway has two outgoing edges with the same normalized condition."""
        from collections import defaultdict
        outgoing: dict[str, list[dict]] = defaultdict(list)
        for e in graph["edges"]:
            outgoing[e["frm"]].append(e)

        for n in graph["nodes"]:
            if n["kind"] != "gateway":
                continue
            nid = n["id"]
            edges = outgoing.get(nid, [])
            seen: dict[str, str] = {}
            for e in edges:
                raw = e.get("condition")
                if raw is None:
                    continue
                norm = normalize_condition(raw)
                if norm is None:
                    continue
                assert norm not in seen, (
                    f"Gateway {nid!r}: edges to {seen[norm]!r} and "
                    f"{e['to']!r} share normalized condition {norm!r}"
                )
                seen[norm] = e["to"]
