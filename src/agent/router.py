"""
router.py
Deterministic edge router for the AP process agent.

``route_edge`` is called by LangGraph's conditional-edge mechanism.
It evaluates each outgoing edge's condition string against the current
APState and returns the target node ID to follow next.

Strict 2-phase evaluation
-------------------------
Phase 1 — Conditional edges (edges with a non-None ``condition``):
  - Evaluate all conditions via the Condition DSL.
  - 1 match  → route to it.
  - >1 match → AMBIGUOUS_ROUTE (fail closed to exception station).
  - 0 matches → proceed to Phase 2.

Phase 2 — Unconditional edges (edges where ``condition`` is None):
  - 1 match  → route to it.
  - >1 match → AMBIGUOUS_ROUTE.
  - 0 matches → NO_ROUTE.

On AMBIGUOUS_ROUTE or NO_ROUTE the router returns the node ID of the
corresponding exception station (looked up dynamically via
``meta.intent_key``).  If the station is missing a ``ValueError`` is
raised.  The unmodeled-logic JSONL logger is called for every such
event.

Trivial short-circuits (single edge, all-same-target) still apply
before the 2-phase logic kicks in.

All condition compilation is done via ``src.conditions.get_predicate``
which normalises, parses, and caches predicates safely (no eval).

Raises
------
RouterError
    When no outgoing edges exist at all.
ValueError
    When an exception station is required but not found in the graph.
"""
from __future__ import annotations

from .state import APState
from ..conditions import get_predicate
from ..unmodeled import record_event


class RouterError(Exception):
    """Raised when no valid outgoing edge can be selected."""


# ---------------------------------------------------------------------------
# Intent keys for exception stations
# ---------------------------------------------------------------------------
_AMBIGUOUS_INTENT = "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"
_NO_ROUTE_INTENT = "task:MANUAL_REVIEW_NO_ROUTE"


# ---------------------------------------------------------------------------
# Station lookup helper
# ---------------------------------------------------------------------------

def _resolve_station(station_map: dict[str, str], intent_key: str) -> str:
    """
    Return the node ID for the exception station matching *intent_key*.

    Raises ``ValueError`` if the station is not in *station_map*.
    """
    node_id = station_map.get(intent_key)
    if node_id is None:
        raise ValueError(
            f"Exception station with intent_key={intent_key!r} not found "
            f"in station_map. Available: {list(station_map.keys())}"
        )
    return node_id


# ---------------------------------------------------------------------------
# Unmodeled-event logger
# ---------------------------------------------------------------------------

def _log_unmodeled(
    reason: str,
    node_data: dict,
    state: APState,
    matched_targets: list[str] | None = None,
) -> None:
    """Log a NO_ROUTE or AMBIGUOUS_ROUTE event (no raw text — privacy)."""
    event = {
        "reason": reason,
        "from_node": node_data.get("id", ""),
        "process_id": state.get("invoice_id", ""),
        "version": (node_data.get("meta") or {}).get("patch_id", ""),
        "state_keys_present": sorted(k for k, v in state.items() if v),
    }
    if matched_targets is not None:
        event["matched_targets"] = matched_targets
    record_event(event)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def route_edge(
    state: APState,
    outgoing_edges: list[dict],
    node_data: dict,
    station_map: dict[str, str] | None = None,
) -> str:
    """
    Return the ``node_id`` of the next node to execute.

    Parameters
    ----------
    state          : current APState snapshot
    outgoing_edges : all edges whose ``frm`` == current node (already deduped)
    node_data      : the full node dict from the process JSON
    station_map    : mapping of ``meta.intent_key`` → node ID for all
                     exception stations.  When ``None``, ambiguous / no-route
                     situations raise ``RouterError`` instead of routing to
                     a station (backward-compat for tests without stations).
    """
    if not outgoing_edges:
        raise RouterError(
            f"Node {node_data['id']!r} has no outgoing edges — "
            "cannot determine next step."
        )

    # --- Trivial: single outgoing edge ---
    if len(outgoing_edges) == 1:
        return outgoing_edges[0]["to"]

    # --- All edges lead to the same target (dedup check) ---
    unique_targets = list(dict.fromkeys(e["to"] for e in outgoing_edges))
    if len(unique_targets) == 1:
        return unique_targets[0]

    # =================================================================
    # Phase 1 — Conditional edges
    # =================================================================
    conditional = [e for e in outgoing_edges if e.get("condition") is not None]
    cond_matches: list[str] = []

    for edge in conditional:
        predicate = get_predicate(edge["condition"])
        if predicate is not None and predicate(state):
            cond_matches.append(edge["to"])

    if len(cond_matches) == 1:
        return cond_matches[0]

    if len(cond_matches) > 1:
        # AMBIGUOUS_ROUTE — multiple conditional edges matched
        _log_unmodeled("AMBIGUOUS_ROUTE", node_data, state, cond_matches)
        if station_map is not None:
            return _resolve_station(station_map, _AMBIGUOUS_INTENT)
        raise RouterError(
            f"Node {node_data['id']!r}: {len(cond_matches)} conditional edges "
            f"matched — ambiguous route: {cond_matches}"
        )

    # =================================================================
    # Phase 2 — Unconditional edges (only when Phase 1 had 0 matches)
    # =================================================================
    unconditional = [e for e in outgoing_edges if e.get("condition") is None]

    if len(unconditional) == 1:
        return unconditional[0]["to"]

    if len(unconditional) > 1:
        # AMBIGUOUS_ROUTE — multiple unconditional edges
        targets = [e["to"] for e in unconditional]
        _log_unmodeled("AMBIGUOUS_ROUTE", node_data, state, targets)
        if station_map is not None:
            return _resolve_station(station_map, _AMBIGUOUS_INTENT)
        raise RouterError(
            f"Node {node_data['id']!r}: {len(unconditional)} unconditional edges "
            f"— ambiguous route: {targets}"
        )

    # =================================================================
    # No matches in either phase → NO_ROUTE
    # =================================================================
    _log_unmodeled("NO_ROUTE", node_data, state)
    if station_map is not None:
        return _resolve_station(station_map, _NO_ROUTE_INTENT)
    raise RouterError(
        f"Node {node_data['id']!r}: no conditional or unconditional edge "
        "matched — no route available."
    )
