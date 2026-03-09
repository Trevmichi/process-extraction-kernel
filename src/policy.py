"""
policy.py
Narrow policy abstraction for the AP extraction workflow.

Centralizes the smallest set of policy surfaces that are already clearly
variable: approval thresholds, PO requirements, required extraction fields,
and exception routing intents.  All consumers read from DEFAULT_POLICY
instead of scattered hardcoded constants.

The default instance reproduces current behavior exactly.  Future phases
may accept PolicyConfig as a parameter for multi-tenant support; for now,
module-level DEFAULT_POLICY is the single source of truth.

Import-time vs runtime
~~~~~~~~~~~~~~~~~~~~~~
Several consumers snapshot DEFAULT_POLICY fields at **import time**:

- ``ontology.APPROVAL_THRESHOLD = DEFAULT_POLICY.approval_threshold``
- ``contracts._REQUIRED_EXTRACTION_FIELDS = DEFAULT_POLICY.required_fields``
- ``router._AMBIGUOUS_INTENT = DEFAULT_POLICY.ambiguous_route_intent``

These are effectively frozen once the module is first imported.  In contrast,
``verifier.py`` reads ``DEFAULT_POLICY.po_mode`` at **call time** (each
invocation).  Tests that mock policy values must patch at the correct level:
the consumer's module-level name, not ``DEFAULT_POLICY`` itself, for the
import-time snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PoMode = Literal["required", "optional", "not_applicable"]


@dataclass(frozen=True)
class PolicyConfig:
    """Immutable policy configuration for AP extraction workflow.

    Fields
    ------
    approval_threshold : int
        Amount above which invoices are escalated to director review.
    po_mode : PoMode
        "required" — missing PO routes to exception station (current default).
        "optional" — no-PO guard edge is not injected; verifier still validates.
        "not_applicable" — no guard edge AND verifier skips has_po entirely.
    required_fields : tuple[str, ...]
        Extraction fields that must be present in LLM output.  Structural
        validation rejects payloads missing any of these.
    ambiguous_route_intent : str
        Graph intent key for the exception station that handles ambiguous
        routing (multiple conditional edges matched).
    no_route_intent : str
        Graph intent key for the exception station that handles no-route
        conditions (zero edges matched in both routing phases).
    """

    approval_threshold: int = 10_000
    po_mode: PoMode = "required"
    required_fields: tuple[str, ...] = ("vendor", "amount", "has_po")
    ambiguous_route_intent: str = "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"
    no_route_intent: str = "task:MANUAL_REVIEW_NO_ROUTE"

    @property
    def approval_condition_above(self) -> str:
        """DSL condition string for amounts exceeding the threshold."""
        return f"amount > {self.approval_threshold}"

    @property
    def approval_condition_at_or_below(self) -> str:
        """DSL condition string for amounts at or below the threshold."""
        return f"amount <= {self.approval_threshold}"


DEFAULT_POLICY = PolicyConfig()
