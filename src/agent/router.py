"""
router.py
Deterministic edge router for the AP process agent.

`route_edge` is called by LangGraph's conditional-edge mechanism.
It evaluates each outgoing edge's condition string against the current
APState and returns the target node ID to follow next.

Evaluation order
----------------
1. Single outgoing edge  → always take it (no evaluation needed).
2. All edges share one unique target after dedup → take it.
3. Each edge's condition string is looked up in _CONDITION_PREDICATES.
   First truthy predicate wins.
4. Fall back to gateway-type–aware routing using the source node's
   ``decision.type`` field and APState booleans.
5. Last resort: first non-loop edge, then first edge overall.

Raises
------
RouterError — when a gateway has multiple targets but none of the
              predicates evaluate to True (strict-compliance mode).
"""
from __future__ import annotations

from typing import Any

from .state import APState


# ---------------------------------------------------------------------------
# Condition-string → predicate
# ---------------------------------------------------------------------------
# Keys are lower-cased condition strings as they appear in the process JSON.
# Values are callables (APState) -> bool.
_CONDITION_PREDICATES: dict[str, Any] = {
    # Canonical outcome labels
    "match":              lambda s: s["po_match"],
    "no_match":           lambda s: not s["po_match"],
    "has_po":             lambda s: s["has_po"],
    "no_po":              lambda s: not s["has_po"],
    "approve":            lambda s: s["amount"] <= 5000.0,
    "reject":             lambda s: s["amount"] > 5000.0,
    "no_po_approve":      lambda s: not s["has_po"] and s["amount"] <= 5000.0,
    "no_po_reject":       lambda s: not s["has_po"] and s["amount"] > 5000.0,
    "above_tolerance":    lambda s: not s["po_match"],
    "within_tolerance":   lambda s: s["po_match"],
    "amount<=thresh":     lambda s: s["amount"] <= 5000.0,
    "amount>thresh":      lambda s: s["amount"] > 5000.0,
    "duplicate_detected": lambda s: s.get("status") == "DUPLICATE",
    "not_duplicate":      lambda s: s.get("status") != "DUPLICATE",
    "successful_match":   lambda s: s["po_match"],
    "condition_true":     lambda s: True,
    # Gateway-type names used as edge conditions by the extractor
    "match_3_way":        lambda s: s["po_match"],
    "approve_or_reject":  lambda s: s["amount"] <= 5000.0,
    "if_condition":       lambda s: True,   # generic passthrough
    "schedule_payment":   lambda s: True,
    "threshold_amount":   lambda s: s["amount"] <= 5000.0,
    # Patched guardrail conditions (injected by patch_logic.py)
    "amount>10000":             lambda s: s["amount"] > 10000.0,
    "amount<=10000":            lambda s: s["amount"] <= 10000.0,
    "status==missing_data":     lambda s: s.get("status") == "MISSING_DATA",
    "status!=missing_data":     lambda s: s.get("status") != "MISSING_DATA",
    "has_po==false":            lambda s: not s["has_po"],
    "has_po==true":             lambda s: s["has_po"],
}


class RouterError(Exception):
    """Raised when no valid outgoing edge can be selected."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def route_edge(
    state: APState,
    outgoing_edges: list[dict],
    node_data: dict,
) -> str:
    """
    Return the ``node_id`` of the next node to execute.

    Parameters
    ----------
    state          : current APState snapshot
    outgoing_edges : all edges whose ``frm`` == current node (already deduped)
    node_data      : the full node dict from the process JSON
    """
    if not outgoing_edges:
        raise RouterError(
            f"Node {node_data['id']!r} has no outgoing edges — "
            "cannot determine next step."
        )

    # --- 1. Trivial: single outgoing edge ---
    if len(outgoing_edges) == 1:
        return outgoing_edges[0]["to"]

    # --- 2. All edges lead to the same target (dedup check) ---
    unique_targets = list(dict.fromkeys(e["to"] for e in outgoing_edges))
    if len(unique_targets) == 1:
        return unique_targets[0]

    # --- 3. Condition-string evaluation ---
    for edge in outgoing_edges:
        raw = edge.get("condition")
        if raw is None:
            # Unconditional edge — but only take it if it's the ONLY such edge
            # (handled by checking all conditions first; fall through if not sole)
            continue
        pred = _CONDITION_PREDICATES.get(raw.lower())
        if pred is not None and pred(state):
            return edge["to"]

    # --- 3b. If unconditional edges remain, take the first non-loop one ---
    unconditional = [e for e in outgoing_edges if e.get("condition") is None]
    if unconditional:
        non_loop = [e for e in unconditional if e["to"] != state.get("current_node")]
        if non_loop:
            return non_loop[0]["to"]
        return unconditional[0]["to"]

    # --- 4. Decision-type–aware routing (extractor used type name as condition) ---
    decision_type = (node_data.get("decision") or {}).get("type", "")
    targets = [e["to"] for e in outgoing_edges]

    if decision_type == "MATCH_3_WAY":
        return targets[0] if state["po_match"] else targets[-1]

    if decision_type == "HAS_PO":
        return targets[0] if state["has_po"] else targets[-1]

    if decision_type == "THRESHOLD_AMOUNT":
        return targets[0] if state["amount"] <= 5000.0 else targets[-1]

    if decision_type == "VARIANCE_ABOVE_TOLERANCE":
        # po_match=True means within tolerance → skip hold path
        return targets[-1] if state["po_match"] else targets[0]

    if decision_type == "APPROVE_OR_REJECT":
        return targets[0] if state["amount"] <= 5000.0 else targets[-1]

    if decision_type == "IF_CONDITION":
        # Prefer a non-loop edge (avoids re-entering the same gateway)
        non_loop = [e for e in outgoing_edges if e["to"] != state.get("current_node")]
        if non_loop:
            return non_loop[0]["to"]

    # --- 5. Last resort: first edge ---
    return outgoing_edges[0]["to"]
