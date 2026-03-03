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
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

# Strict Literal type for 3-way match outcomes
MatchResult = Literal["MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"]


class APState(TypedDict):
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
    raw_text:         str
    extraction:       dict
    provenance:       dict
