from __future__ import annotations
from typing import Literal, Set

from .policy import DEFAULT_POLICY

# ---------------------------------------------------------------------------
# ACTIONS (Tasks) — core AP action verbs
# ---------------------------------------------------------------------------
ActionType = Literal[
    # Core AP actions (mined from process documents)
    "RECEIVE_MESSAGE",
    "ENTER_RECORD",
    "VALIDATE_FIELDS",
    "MATCH_3_WAY",
    "ROUTE_FOR_REVIEW",
    "REVIEW",
    "UPDATE_RECORD",
    "APPROVE",
    "REJECT",
    "UPDATE_STATUS",
    "REQUEST_CLARIFICATION",
    "SCHEDULE_PAYMENT",
    "EXECUTE_PAYMENT",
    "NOTIFY",
    # Synthetic / patch-injected intents
    "ESCALATE_TO_DIRECTOR",
    "CRITIC_RETRY",
    "REJECT_INVOICE",
    "MANUAL_REVIEW_NO_PO",
    "MANUAL_REVIEW_MATCH_FAILED",
    "MANUAL_REVIEW_UNMODELED_GATE",
    "MANUAL_REVIEW_AMBIGUOUS_ROUTE",
    "MANUAL_REVIEW_NO_ROUTE",
    "SEQUENTIAL_DISPATCH",
]

# ---------------------------------------------------------------------------
# DECISIONS (Gateways) — routing decision types
# ---------------------------------------------------------------------------
DecisionType = Literal[
    # Mined gateway types
    "MATCH_3_WAY",
    "THRESHOLD_AMOUNT",
    "HAS_PO",
    "VARIANCE_ABOVE_TOLERANCE",
    "APPROVE_OR_REJECT",
    "IF_CONDITION",
    # Synthetic gateway types (added by patch/normalize)
    "MATCH_DECISION",
    "THRESHOLD_AMOUNT_10K",
]

# ---------------------------------------------------------------------------
# CONDITIONS (Legacy edge labels — mined from process documents)
# ---------------------------------------------------------------------------
ConditionType = Literal[
    "match",
    "no_match",
    "approve",
    "reject",
    "has_po",
    "no_po",
    "above_tolerance",
    "within_tolerance",
]

# ---------------------------------------------------------------------------
# STATUS — pipeline state transitions
# ---------------------------------------------------------------------------
StatusType = Literal[
    # Transitional (mid-pipeline)
    "NEW",
    "DATA_EXTRACTED",
    "NEEDS_RETRY",
    "VALIDATED",
    "PENDING_INFO",
    # Terminal — success
    "APPROVED",
    "PAID",
    "CLOSED",
    # Terminal — failure / rejection
    "REJECTED",
    "ESCALATED",
    "BAD_EXTRACTION",
    "MISSING_DATA",
    # Exception (fail-closed sinks)
    "EXCEPTION_BAD_EXTRACTION",
    "EXCEPTION_UNMODELED_GATE",
    "EXCEPTION_AMBIGUOUS_ROUTE",
    "EXCEPTION_NO_ROUTE",
    "EXCEPTION_NO_PO",
    "EXCEPTION_MATCH_FAILED",
    "EXCEPTION_UNMODELED",
    "EXCEPTION_UNKNOWN",
]

# ---------------------------------------------------------------------------
# ACTORS
# ---------------------------------------------------------------------------
ActorId = Literal[
    "role_ap_clerk",
    "role_manager",
    "role_director",
    "sys_erp",
]

# ---------------------------------------------------------------------------
# ARTIFACTS
# ---------------------------------------------------------------------------
ArtifactId = Literal[
    "art_invoice",
    "art_po",
    "art_grn",
    "art_payment",
    "art_account_code",
    "art_corrected_docs",
    "",
]

# ---------------------------------------------------------------------------
# Runtime validation sets (do NOT depend on __args__)
# ---------------------------------------------------------------------------

VALID_ACTIONS: Set[str] = {
    # Core
    "RECEIVE_MESSAGE", "ENTER_RECORD", "VALIDATE_FIELDS", "MATCH_3_WAY",
    "ROUTE_FOR_REVIEW", "REVIEW", "UPDATE_RECORD", "APPROVE", "REJECT",
    "UPDATE_STATUS", "REQUEST_CLARIFICATION", "SCHEDULE_PAYMENT",
    "EXECUTE_PAYMENT", "NOTIFY",
    # Synthetic / patch-injected
    "ESCALATE_TO_DIRECTOR", "CRITIC_RETRY", "REJECT_INVOICE",
    "MANUAL_REVIEW_NO_PO", "MANUAL_REVIEW_MATCH_FAILED",
    "MANUAL_REVIEW_UNMODELED_GATE", "MANUAL_REVIEW_AMBIGUOUS_ROUTE",
    "MANUAL_REVIEW_NO_ROUTE", "SEQUENTIAL_DISPATCH",
    # Alias entries (normalised before graph build)
    "ENTER_DATA",
    # Catch-all sentinel written by Action.__post_init__
    "UNKNOWN_ACTION",
}

VALID_DECISIONS: Set[str] = {
    # Mined
    "MATCH_3_WAY", "THRESHOLD_AMOUNT", "HAS_PO",
    "VARIANCE_ABOVE_TOLERANCE", "APPROVE_OR_REJECT", "IF_CONDITION",
    # Synthetic
    "MATCH_DECISION", "THRESHOLD_AMOUNT_10K",
    # Catch-all sentinel
    "UNKNOWN_DECISION",
}

VALID_CONDITIONS: Set[str] = {
    "match", "no_match", "approve", "reject",
    "has_po", "no_po", "above_tolerance", "within_tolerance",
}

VALID_STATUSES: frozenset[str] = frozenset({
    # Transitional
    "NEW", "DATA_EXTRACTED", "NEEDS_RETRY", "VALIDATED", "PENDING_INFO",
    # Terminal — success
    "APPROVED", "PAID", "CLOSED",
    # Terminal — failure / rejection
    "REJECTED", "ESCALATED", "BAD_EXTRACTION", "MISSING_DATA",
    # Exception
    "EXCEPTION_BAD_EXTRACTION", "EXCEPTION_UNMODELED_GATE",
    "EXCEPTION_AMBIGUOUS_ROUTE", "EXCEPTION_NO_ROUTE",
    "EXCEPTION_NO_PO", "EXCEPTION_MATCH_FAILED", "EXCEPTION_UNMODELED",
    "EXCEPTION_UNKNOWN",
})

TERMINAL_STATUSES: frozenset[str] = frozenset({
    # Success
    "APPROVED", "PAID", "CLOSED",
    # Failure / rejection
    "REJECTED", "ESCALATED", "BAD_EXTRACTION", "MISSING_DATA",
    # Exception
    "EXCEPTION_BAD_EXTRACTION", "EXCEPTION_UNMODELED_GATE",
    "EXCEPTION_AMBIGUOUS_ROUTE", "EXCEPTION_NO_ROUTE",
    "EXCEPTION_NO_PO", "EXCEPTION_MATCH_FAILED", "EXCEPTION_UNMODELED",
    "EXCEPTION_UNKNOWN",
})

EXCEPTION_STATUSES: frozenset[str] = frozenset({
    "EXCEPTION_BAD_EXTRACTION", "EXCEPTION_UNMODELED_GATE",
    "EXCEPTION_AMBIGUOUS_ROUTE", "EXCEPTION_NO_ROUTE",
    "EXCEPTION_NO_PO", "EXCEPTION_MATCH_FAILED", "EXCEPTION_UNMODELED",
    "EXCEPTION_UNKNOWN",
})

# Gateway types that the normalizer recognizes as structured (not fan-out)
KNOWN_STRUCTURED_GATEWAY_TYPES: frozenset[str] = frozenset({
    "MATCH_3_WAY", "MATCH_DECISION", "HAS_PO",
    "APPROVE_OR_REJECT", "THRESHOLD_AMOUNT_10K",
})

# Approval threshold — delegated to policy layer (src/policy.py).
# Pre-built condition strings avoid f-string assembly at consumer sites.
APPROVAL_THRESHOLD: int = DEFAULT_POLICY.approval_threshold
CONDITION_AMOUNT_ABOVE_THRESHOLD: str = DEFAULT_POLICY.approval_condition_above
CONDITION_AMOUNT_AT_OR_BELOW_THRESHOLD: str = DEFAULT_POLICY.approval_condition_at_or_below

VALID_ACTORS: Set[str] = {"role_ap_clerk", "role_manager", "role_director", "sys_erp"}
VALID_ARTIFACTS: Set[str] = {
    "art_invoice", "art_po", "art_grn", "art_payment",
    "art_account_code", "art_corrected_docs", "",
}
