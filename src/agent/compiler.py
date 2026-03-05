"""
compiler.py
Compile an extracted AP process JSON into a LangGraph CompiledGraph.

`build_ap_graph(json_path)` reads the JSON produced by the extraction
pipeline, validates it with the graph linter, registers every process node
as a LangGraph node, wires edges (both unconditional and conditional via
the router), and returns a compiled, executable StateGraph.

Edge handling
-------------
* The graph is validated by ``assert_graph_valid`` before any compilation.
  Graphs with errors (missing artifacts, gateway fan-out, bad conditions)
  fail loudly with a detailed lint report.
* Duplicate (frm, to) pairs are deduplicated — first occurrence wins.
* Nodes with a single unique outgoing target use ``add_edge`` (fast path).
* Nodes with multiple unique targets use ``add_conditional_edges`` backed
  by ``route_edge`` from router.py.
* End-kind nodes are connected to LangGraph's ``END`` sentinel.
* Unreachable orphan nodes in the JSON are still added to the graph (they
  are simply never visited during execution).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Hashable

from langgraph.graph import END, StateGraph

from ..linter import assert_graph_valid
from .nodes import create_node_handler
from .router import route_edge
from .state import APState


def build_ap_graph(json_path: str) -> Any:
    """Compile and return a LangGraph graph from *json_path*.

    Args:
      json_path(path to an ``ap_*_auto.json`` file produced by the): extraction pipeline.
      json_path: str:
      json_path: str: 

    Returns:
      : 

    """
    data: dict = json.loads(Path(json_path).read_text(encoding="utf-8"))

    # ---- Graph validation (fail closed) ------------------------------------
    assert_graph_valid(data)

    nodes: list[dict]     = data["nodes"]
    raw_edges: list[dict] = data["edges"]

    # ---- index ---------------------------------------------------------------
    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # Deduplicate edges by (frm, to) — first occurrence wins.
    # (The linter already errors on true duplicates; dedup here is a safety
    # net for any edge that becomes identical only after normalization.)
    seen_pairs: set[tuple[str, str]] = set()
    edges: list[dict] = []
    for e in raw_edges:
        pair = (e["frm"], e["to"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            edges.append(e)

    # Group outgoing edges by source node id; preserve insertion order
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        outgoing[e["frm"]].append(e)

    # ---- locate START and END nodes ------------------------------------------
    start_node_id: str = next(
        (
            n["id"] for n in nodes
            if (n.get("meta") or {}).get("canonical_key") == "event:start"
        ),
        nodes[0]["id"],
    )
    end_node_ids: set[str] = {
        n["id"] for n in nodes
        if n["kind"] == "end"
        or (n.get("meta") or {}).get("canonical_key") == "end:end"
    }

    # ---- Build exception station map (intent_key → node_id) -----------------
    station_map: dict[str, str] = {}
    station_node_ids: set[str] = set()
    for n in nodes:
        meta = n.get("meta") or {}
        ik = meta.get("intent_key") or meta.get("canonical_key", "")
        if ik.startswith("task:MANUAL_REVIEW_"):
            station_map[ik] = n["id"]
            station_node_ids.add(n["id"])

    # ---- build the StateGraph ------------------------------------------------
    graph: StateGraph = StateGraph(APState)
    graph_any: Any = graph

    # Register every node from the JSON
    for node in nodes:
        nid     = node["id"]
        handler = create_node_handler(nid, node, outgoing.get(nid, []))
        graph_any.add_node(nid, handler)

    # Wire edges
    for nid, node in node_by_id.items():
        out_edges = outgoing.get(nid, [])

        # End nodes always route to LangGraph END
        if nid in end_node_ids:
            graph.add_edge(nid, END)
            continue

        # No outgoing edges in JSON → treat as terminal
        if not out_edges:
            graph.add_edge(nid, END)
            continue

        # Unique set of target node IDs (stable, insertion order)
        unique_targets = list(dict.fromkeys(e["to"] for e in out_edges))

        if len(unique_targets) == 1:
            # ---- Unconditional single edge -----------------------------------
            target = unique_targets[0]
            graph.add_edge(nid, END if target in end_node_ids else target)

        else:
            # ---- Conditional routing -----------------------------------------
            # Build path_map: routing-fn return value → LangGraph node name
            path_map: dict[Hashable, str] = {
                t: (END if t in end_node_ids else t)
                for t in unique_targets
            }

            # Add exception station IDs so the router can fail-closed to them
            for sid in station_node_ids:
                if sid not in path_map:
                    path_map[sid] = (END if sid in end_node_ids else sid)

            # Curry router with this node's edges + data + station map
            def _make_router(
                bound_edges: list[dict],
                bound_node: dict,
                bound_stations: dict[str, str],
            ):
                """

                Args:
                  bound_edges: list[dict]:
                  bound_node: dict:
                  bound_stations: dict[str:
                  str]: 
                  bound_edges: list[dict]: 
                  bound_node: dict: 
                  bound_stations: dict[str: 

                Returns:

                """
                def _route(state: APState) -> str:
                    """

                    Args:
                      state: APState:
                      state: APState: 

                    Returns:

                    """
                    return route_edge(
                        state, bound_edges, bound_node, bound_stations
                    )
                _route.__name__ = f"route_{bound_node['id']}"
                return _route

            graph_any.add_conditional_edges(
                nid,
                _make_router(out_edges, node, station_map),
                path_map,
            )

    # Connect LangGraph START to the process entry node
    graph.set_entry_point(start_node_id)

    return graph.compile()
