"""
tests/test_production_graph_regressions.py
Golden regression tests for the production patched graph.

Loads ``outputs/ap_master_manual_auto_patched.json`` and asserts structural
invariants that must hold after patching + normalisation.  These tests catch
regressions in pass ordering, node injection, and gateway wiring.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

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

    def test_node_count_lower_bound(self, graph: dict):
        assert len(graph["nodes"]) >= 34

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

        assert counts["MANUAL_REVIEW_MATCH_FAILED"] >= 1
        assert counts["MANUAL_REVIEW_UNMODELED_GATE"] >= 1
        assert counts["MANUAL_REVIEW_NO_PO"] >= 1
        assert counts["ROUTE_FOR_REVIEW"] >= 1
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
        assert len(seq_nodes) >= 1

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


# ===========================================================================
# Structural invariants (shape-based, not count-based)
# ===========================================================================

# Terminal node exemptions: these action types represent explicit terminal
# sinks (manual review stations, exception routes).  They are wired to END
# by the compiler, not by JSON edges.
_TERMINAL_ACTION_TYPES = frozenset({
    "MANUAL_REVIEW_MATCH_FAILED",
    "MANUAL_REVIEW_UNMODELED_GATE",
    "MANUAL_REVIEW_NO_PO",
    "MANUAL_REVIEW_AMBIGUOUS_ROUTE",
    "ROUTE_FOR_REVIEW",
})


class TestStructuralInvariants:

    def test_every_gateway_has_distinct_conditions(self, graph: dict):
        """Every gateway has >= 2 outgoing edges with distinct conditions."""
        from collections import defaultdict
        outgoing: dict[str, list[dict]] = defaultdict(list)
        for e in graph["edges"]:
            outgoing[e["frm"]].append(e)

        for n in graph["nodes"]:
            if n["kind"] != "gateway":
                continue
            nid = n["id"]
            edges = outgoing.get(nid, [])
            assert len(edges) >= 2, (
                f"Gateway {nid!r} has {len(edges)} outgoing edge(s), need >= 2"
            )
            norms = [normalize_condition(e.get("condition")) for e in edges]
            non_null = [c for c in norms if c is not None]
            assert len(non_null) == len(set(non_null)), (
                f"Gateway {nid!r} has duplicate normalized conditions"
            )

    def test_every_gateway_has_outgoing_edges(self, graph: dict):
        """Every gateway node has at least 2 outgoing edges (already tested above
        via distinct conditions, but this is the structural minimum)."""
        from collections import defaultdict
        outgoing: dict[str, list[dict]] = defaultdict(list)
        for e in graph["edges"]:
            outgoing[e["frm"]].append(e)

        for n in graph["nodes"]:
            if n["kind"] != "gateway":
                continue
            nid = n["id"]
            assert nid in outgoing and len(outgoing[nid]) >= 2, (
                f"Gateway {nid!r} has fewer than 2 outgoing edges"
            )

    def test_start_node_exists(self, graph: dict):
        """Exactly 1 node with canonical_key 'event:start'."""
        starts = [
            n for n in graph["nodes"]
            if (n.get("meta") or {}).get("canonical_key") == "event:start"
        ]
        assert len(starts) == 1

    def test_end_node_exists(self, graph: dict):
        """At least 1 end node."""
        ends = [n for n in graph["nodes"] if n["kind"] == "end"]
        assert len(ends) >= 1

    def test_main_flow_reachable_from_start(self, graph: dict):
        """Key process nodes are reachable from start via BFS."""
        from collections import defaultdict, deque
        adj: dict[str, list[str]] = defaultdict(list)
        for e in graph["edges"]:
            adj[e["frm"]].append(e["to"])

        # Find start node
        start_id = None
        for n in graph["nodes"]:
            ck = (n.get("meta") or {}).get("canonical_key", "")
            if ck == "event:start":
                start_id = n["id"]
                break
        assert start_id is not None

        # BFS
        visited: set[str] = set()
        queue: deque[str] = deque([start_id])
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            queue.extend(adj.get(nid, []))

        # Key structural nodes must be reachable
        nodes_map = {n["id"]: n for n in graph["nodes"]}
        for nid in ("n_threshold", "n5_decision"):
            assert nid in visited, (
                f"Gateway {nid!r} not reachable from start"
            )
        # At least one end node reachable
        end_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "end"}
        assert visited & end_ids, "No end node reachable from start"

    def test_no_self_loops(self, graph: dict):
        """No edge has frm == to."""
        for e in graph["edges"]:
            assert e["frm"] != e["to"], (
                f"Self-loop detected: {e['frm']!r} -> {e['to']!r}"
            )


# ===========================================================================
# Graph determinism fingerprint
# ===========================================================================

# Update this hash ONLY when you intentionally change the production graph
# topology (node set, edge set, or their structural attributes).
# To regenerate:
#   python -c "
#   import hashlib, json
#   data = json.loads(open('outputs/ap_master_manual_auto_patched.json').read())
#   node_tuples = sorted((n['id'], n['kind'],
#       (n.get('action') or {}).get('type','') or (n.get('decision') or {}).get('type',''),
#       (n.get('meta') or {}).get('canonical_key','')) for n in data['nodes'])
#   edge_tuples = sorted((e['frm'], e.get('condition') or '', e['to']) for e in data['edges'])
#   fp = json.dumps({'nodes': node_tuples, 'edges': edge_tuples}, sort_keys=True)
#   print(hashlib.sha256(fp.encode()).hexdigest())
#   "
_EXPECTED_GRAPH_FINGERPRINT = "a47585833c514e2daa5713011bf7d2a399f7d97ef2b4b598b85c1d57b0c169c5"


class TestGraphDeterminism:

    def test_fingerprint_stable(self, graph: dict):
        """Normalized production graph topology must not change unintentionally."""
        node_tuples = sorted(
            (n["id"], n["kind"],
             (n.get("action") or {}).get("type", "")
             or (n.get("decision") or {}).get("type", ""),
             (n.get("meta") or {}).get("canonical_key", ""))
            for n in graph["nodes"]
        )
        edge_tuples = sorted(
            (e["frm"], e.get("condition") or "", e["to"])
            for e in graph["edges"]
        )
        fingerprint_input = json.dumps(
            {"nodes": node_tuples, "edges": edge_tuples}, sort_keys=True
        )
        actual = hashlib.sha256(fingerprint_input.encode()).hexdigest()
        assert actual == _EXPECTED_GRAPH_FINGERPRINT, (
            f"Graph topology changed!\n"
            f"  Expected: {_EXPECTED_GRAPH_FINGERPRINT}\n"
            f"  Actual:   {actual}\n"
            f"If intentional, update _EXPECTED_GRAPH_FINGERPRINT."
        )
