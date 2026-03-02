"""
state.py
APState — the shared state schema for the LangGraph AP process agent.

Every node in the compiled graph receives this TypedDict and returns
a partial update dict.  LangGraph merges deltas; the `audit_log` field
uses Annotated with operator.add so each step's log entries accumulate
rather than overwrite.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class APState(TypedDict):
    invoice_id:       str
    vendor:           str
    amount:           float
    has_po:           bool
    po_match:         bool
    status:           str
    current_node:     str
    audit_log:        Annotated[list[str], operator.add]
    raw_invoice_text: str
