from __future__ import annotations
from typing import Literal, Set

# --- ACTIONS (Tasks) ---
ActionType = Literal[
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
]

# --- DECISIONS (Gateways) ---
DecisionType = Literal[
    "MATCH_3_WAY",
    "THRESHOLD_AMOUNT",
    "HAS_PO",
    "VARIANCE_ABOVE_TOLERANCE",
    "APPROVE_OR_REJECT",
    "IF_CONDITION",
]

# --- CONDITIONS (Edge Labels) ---
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

# --- ACTORS ---
ActorId = Literal[
    "role_ap_clerk",
    "role_manager",
    "role_director",
    "sys_erp",
]

# --- ARTIFACTS ---
ArtifactId = Literal[
    "art_invoice",
    "art_po",
    "art_grn",
    "art_payment",
    "art_account_code",
    "art_corrected_docs",
    "",
]

# Runtime validation sets (do NOT depend on __args__)
VALID_ACTIONS: Set[str] = {
    "RECEIVE_MESSAGE","ENTER_RECORD","VALIDATE_FIELDS","MATCH_3_WAY","ROUTE_FOR_REVIEW","REVIEW",
    "UPDATE_RECORD","APPROVE","REJECT","UPDATE_STATUS","REQUEST_CLARIFICATION","SCHEDULE_PAYMENT",
    "EXECUTE_PAYMENT","NOTIFY"
}
VALID_DECISIONS: Set[str] = {
    "MATCH_3_WAY","THRESHOLD_AMOUNT","HAS_PO","VARIANCE_ABOVE_TOLERANCE","APPROVE_OR_REJECT","IF_CONDITION"
}
VALID_CONDITIONS: Set[str] = {
    "match","no_match","approve","reject","has_po","no_po","above_tolerance","within_tolerance"
}
VALID_ACTORS: Set[str] = {"role_ap_clerk","role_manager","role_director","sys_erp"}
VALID_ARTIFACTS: Set[str] = {"art_invoice","art_po","art_grn","art_payment","art_account_code","art_corrected_docs",""}
