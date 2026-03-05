"""
state.py
APState — the shared state schema for the LangGraph AP process agent.

Every node in the compiled graph receives this TypedDict and returns
a partial update dict.  LangGraph merges deltas; the `audit_log` field
uses Annotated with operator.add so each step's log entries accumulate
rather than overwrite.

Fields
------
match_3_way : bool
    Result of the 3-way match step.  Set by the MATCH_3_WAY task node
    (mirrors ``po_match`` until ERP integration is available).
    Gateway conditions ``match_3_way == true / false`` read this field.

extraction : dict
    Raw nested LLM payload from ENTER_RECORD.  Stores the evidence-backed
    extraction before verification.  Always written (even on failure).

provenance : dict
    Validation metadata from the deterministic verifier.  Per-field
    grounding results with consistent sub-keys.

raw_text : str
    Original invoice/PO text for extraction (canonical key).

last_gateway : str
    Node ID of the most recent gateway that made a routing decision.
    Set by gateway node execution; read by exception stations to log
    which decision point triggered the exception.

retry_count : int
    Number of critic retry attempts executed.  Starts at 0; incremented by
    CRITIC_RETRY node.  ENTER_RECORD reads this to decide between
    ``NEEDS_RETRY`` (first failure) and ``BAD_EXTRACTION`` (already retried).

failure_codes : list[str]
    Verifier failure codes from the most recent extraction attempt.
    Written by ENTER_RECORD and CRITIC_RETRY; read by CRITIC_RETRY to
    build the forensic correction prompt.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict, cast

# Strict Literal type for 3-way match outcomes
MatchResult = Literal["MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"]


class APState(TypedDict):
    """Canonical LangGraph state payload for AP process execution."""
    invoice_id:       str
    vendor:           str
    amount:           float
    has_po:           bool
    po_match:         bool
    match_3_way:      bool           # legacy flag (mirrors po_match)
    match_result:     MatchResult    # strict outcome of 3-way match step
    status:           str
    current_node:     str
    last_gateway:     str
    audit_log:        Annotated[list[str], operator.add]
    route_records:    Annotated[list[dict], operator.add]
    raw_text:         str
    extraction:       dict
    provenance:       dict
    retry_count:      int
    failure_codes:    list[str]


# ---------------------------------------------------------------------------
# Canonical default template — single source of truth for field names + safe
# defaults.  REQUIRED_KEYS is derived from this dict, not from TypedDict
# annotations.
# ---------------------------------------------------------------------------

DEFAULT_STATE_TEMPLATE: APState = {
    "invoice_id":   "",
    "vendor":       "",
    "amount":       0.0,
    "has_po":       False,
    "po_match":     False,
    "match_3_way":  False,
    "match_result": "UNKNOWN",
    "status":       "NEW",
    "current_node": "",
    "last_gateway": "",
    "audit_log":    [],
    "route_records": [],
    "raw_text":     "",
    "extraction":   {},
    "provenance":   {},
    "retry_count":  0,
    "failure_codes": [],
}

REQUIRED_KEYS: frozenset[str] = frozenset(DEFAULT_STATE_TEMPLATE.keys())


def make_initial_state(
    *,
    invoice_id: str,
    raw_text: str,
    po_match: bool = False,
    match_3_way: bool | None = None,
) -> APState:
    """Create a fresh APState with safe defaults from ``DEFAULT_STATE_TEMPLATE``.

    Args:
      *: 
      invoice_id: str:
      raw_text: str:
      po_match: bool:  (Default value = False)
      match_3_way: bool | None:  (Default value = None)
      invoice_id: str: 
      raw_text: str: 
      po_match: bool:  (Default value = False)
      match_3_way: bool | None:  (Default value = None)

    Returns:

    """
    if match_3_way is None:
        match_3_way = po_match

    state = cast(APState, DEFAULT_STATE_TEMPLATE.copy())   # shallow copy
    # Refresh mutable defaults so callers don't share state
    state["audit_log"] = []
    state["route_records"] = []
    state["extraction"] = {}
    state["provenance"] = {}
    state["failure_codes"] = []
    # Apply overrides
    state["invoice_id"] = invoice_id
    state["raw_text"] = raw_text
    state["po_match"] = po_match
    state["match_3_way"] = match_3_way
    return state
