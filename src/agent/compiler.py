"""
compiler.py
Compile an extracted AP process JSON into a LangGraph CompiledGraph.

`build_ap_graph(json_path)` reads the JSON produced by the extraction
pipeline, registers every process node as a LangGraph node, wires edges
(both unconditional and conditional via the router), and returns a
compiled, executable StateGraph.

Edge handling
-------------
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

from langgraph.graph import END, StateGraph

from .nodes import create_node_handler
from .router import route_edge
from .state import APState


def build_ap_graph(json_path: str):
    """
    Compile and return a LangGraph graph from *json_path*.

    Parameters
    ----------
    json_path : path to an ``ap_*_auto.json`` file produced by the
                extraction pipeline.

    Returns
    -------
    A compiled LangGraph ``CompiledGraph`` ready for ``.invoke()``.
    """
    data: dict = json.loads(Path(json_path).read_text(encoding="utf-8"))
    nodes: list[dict]     = data["nodes"]
    raw_edges: list[dict] = data["edges"]

    # ---- index ---------------------------------------------------------------
    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # Deduplicate edges by (frm, to) — first occurrence wins
    seen_pairs: set[tuple[str, str]] = set()
    edges: list[dict] = []
    for e in raw_edges:
        pair = (e["frm"], e["to"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            edges.append(e)

    # Group outgoing edges by source node id
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

    # ---- build the StateGraph ------------------------------------------------
    graph: StateGraph = StateGraph(APState)

    # Register every node from the JSON
    for node in nodes:
        nid     = node["id"]
        handler = create_node_handler(nid, node)
        graph.add_node(nid, handler)

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

        # Unique set of target node IDs
        unique_targets = list(dict.fromkeys(e["to"] for e in out_edges))

        if len(unique_targets) == 1:
            # ---- Unconditional single edge -----------------------------------
            target = unique_targets[0]
            graph.add_edge(nid, END if target in end_node_ids else target)

        else:
            # ---- Conditional routing -----------------------------------------
            # Build path_map: routing-fn return value → LangGraph node name
            path_map: dict[str, str] = {
                t: (END if t in end_node_ids else t)
                for t in unique_targets
            }

            # Curry router with this node's edges + data (closure over locals)
            def _make_router(bound_edges: list[dict], bound_node: dict):
                def _route(state: APState) -> str:
                    return route_edge(state, bound_edges, bound_node)
                _route.__name__ = f"route_{bound_node['id']}"
                return _route

            graph.add_conditional_edges(
                nid,
                _make_router(out_edges, node),
                path_map,
            )

    # Connect LangGraph START to the process entry node
    graph.set_entry_point(start_node_id)

    return graph.compile()
