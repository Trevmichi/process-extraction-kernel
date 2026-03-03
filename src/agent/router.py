"""
router.py
Deterministic edge router for the AP process agent.

``route_edge`` is called by LangGraph's conditional-edge mechanism.
It evaluates each outgoing edge's condition string against the current
APState and returns the target node ID to follow next.

The core evaluation logic lives in ``analyze_routing()`` — a **pure**
function that returns a structured ``RouteResult`` without side effects.
``route_edge`` is a thin wrapper that delegates to ``analyze_routing``,
then handles station resolution and JSONL logging for exception cases.

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

RouteResult.candidates[].matched semantics (frozen)
----------------------------------------------------
- Conditional edges: ``True`` (evaluated true) / ``False`` (evaluated false)
- Unconditional edges: always ``None`` — never True/False
- Short-circuited paths (single_edge, all_same_target): all ``None``
- Selection of unconditional fallback communicated via
  ``reason="unconditional_fallback"`` + ``selected``, not matched=True

Raises
------
RouterError
    When no outgoing edges exist at all.
ValueError
    When an exception station is required but not found in the graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .state import APState
from ..conditions import get_predicate
from ..unmodeled import record_event


class RouterError(Exception):
    """Raised when no valid outgoing edge can be selected."""


# ---------------------------------------------------------------------------
# RouteResult — structured output from analyze_routing()
# ---------------------------------------------------------------------------

@dataclass
class RouteResult:
    """Structured result from ``analyze_routing()``."""
    selected: str | None
    """Target node ID, or None when ambiguous_route / no_route."""
    reason: str
    """One of: single_edge, all_same_target, condition_match,
    unconditional_fallback, ambiguous_route, no_route."""
    candidates: list[dict] = field(default_factory=list)
    """[{"to": str, "condition": str|None, "matched": bool|None}]"""


# ---------------------------------------------------------------------------
# Pure routing analysis
# ---------------------------------------------------------------------------

def analyze_routing(
    state: APState,
    outgoing_edges: list[dict],
) -> RouteResult:
    """
    Pure routing analysis — no side effects, no station resolution.

    Evaluates outgoing edges against *state* and returns a structured
    ``RouteResult``.  ``selected`` is ``None`` for ambiguous_route / no_route;
    the caller handles station resolution and logging.

    Raises ``RouterError`` if *outgoing_edges* is empty.
    """
    if not outgoing_edges:
        raise RouterError("No outgoing edges — cannot determine next step.")

    # --- Trivial: single outgoing edge ---
    if len(outgoing_edges) == 1:
        e = outgoing_edges[0]
        return RouteResult(
            selected=e["to"],
            reason="single_edge",
            candidates=[{"to": e["to"], "condition": e.get("condition"),
                         "matched": None}],
        )

    # --- All edges lead to the same target ---
    unique_targets = list(dict.fromkeys(e["to"] for e in outgoing_edges))
    if len(unique_targets) == 1:
        return RouteResult(
            selected=unique_targets[0],
            reason="all_same_target",
            candidates=[{"to": e["to"], "condition": e.get("condition"),
                         "matched": None} for e in outgoing_edges],
        )

    # =================================================================
    # Phase 1 — Conditional edges
    # =================================================================
    candidates: list[dict] = []
    cond_matches: list[str] = []

    conditional = [e for e in outgoing_edges if e.get("condition") is not None]
    unconditional = [e for e in outgoing_edges if e.get("condition") is None]

    for edge in conditional:
        predicate = get_predicate(edge["condition"])
        matched = predicate is not None and predicate(state)
        candidates.append({
            "to": edge["to"],
            "condition": edge["condition"],
            "matched": matched,
        })
        if matched:
            cond_matches.append(edge["to"])

    # Unconditional edges always have matched=None
    for edge in unconditional:
        candidates.append({
            "to": edge["to"],
            "condition": None,
            "matched": None,
        })

    if len(cond_matches) == 1:
        return RouteResult(
            selected=cond_matches[0],
            reason="condition_match",
            candidates=candidates,
        )

    if len(cond_matches) > 1:
        return RouteResult(
            selected=None,
            reason="ambiguous_route",
            candidates=candidates,
        )

    # =================================================================
    # Phase 2 — Unconditional edges (Phase 1 had 0 matches)
    # =================================================================
    if len(unconditional) == 1:
        return RouteResult(
            selected=unconditional[0]["to"],
            reason="unconditional_fallback",
            candidates=candidates,
        )

    if len(unconditional) > 1:
        return RouteResult(
            selected=None,
            reason="ambiguous_route",
            candidates=candidates,
        )

    # =================================================================
    # No matches in either phase → NO_ROUTE
    # =================================================================
    return RouteResult(
        selected=None,
        reason="no_route",
        candidates=candidates,
    )


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

    Delegates to ``analyze_routing()`` for the pure evaluation, then
    handles station resolution and JSONL logging for exception cases.

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
    result = analyze_routing(state, outgoing_edges)

    if result.selected is not None:
        return result.selected

    # --- Exception: ambiguous_route or no_route ---
    matched_targets = [
        c["to"] for c in result.candidates if c.get("matched") is True
    ]
    _log_unmodeled(
        result.reason.upper(), node_data, state,
        matched_targets or None,
    )

    if station_map is not None:
        intent = (
            _AMBIGUOUS_INTENT if result.reason == "ambiguous_route"
            else _NO_ROUTE_INTENT
        )
        return _resolve_station(station_map, intent)

    raise RouterError(
        f"Node {node_data['id']!r}: {result.reason} — "
        f"candidates: {result.candidates}"
    )
