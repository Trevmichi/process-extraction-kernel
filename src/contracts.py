"""
contracts.py
Typed contracts for extraction payloads and verifier provenance.

These TypedDicts describe the runtime shapes produced by the LLM extraction
layer (ENTER_RECORD / CRITIC_RETRY) and consumed by the verifier.  They exist
for documentation, static analysis, and shape-validation tests — not for
runtime enforcement (the verifier handles that).
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Node meta keys (soft contract — no TypedDict, too heterogeneous)
#
# Known stable keys and their producers/consumers:
#   canonical_key   — canonicalize.py, normalize_graph.py → nodes.py, compiler.py
#   intent_key      — normalize_graph.py → compiler.py (station_map), router.py
#   synthetic       — normalize_graph.py, patch_logic.py → tests
#   patch_id        — normalize_graph.py, patch_logic.py → tests, invariants.py
#   rationale       — normalize_graph.py, patch_logic.py → tests
#   origin          — normalize_graph.py, patch_logic.py → tests
#   origin_pass     — normalize_graph.py → invariants.py
#   semantic_assumption — normalize_graph.py → invariants.py
#   synthetic_edges — normalize_graph.py → invariants.py
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Extraction payload (LLM → verifier)
# ---------------------------------------------------------------------------

class FieldExtraction(TypedDict):
    """Single extracted field: claimed value + verbatim evidence span."""
    value: Any          # str | float | bool | None
    evidence: str


class ExtractionPayload(TypedDict, total=False):
    """Shape returned by _call_llm_json() for ENTER_RECORD / CRITIC_RETRY.

    Required fields: vendor, amount, has_po.
    Optional fields: invoice_date, tax_amount (present when LLM supports them).
    _error is present only on LLM invocation failure.
    """
    vendor: FieldExtraction
    amount: FieldExtraction
    has_po: FieldExtraction
    invoice_date: FieldExtraction
    tax_amount: FieldExtraction
    _error: str


# ---------------------------------------------------------------------------
# Provenance report (verifier output)
# ---------------------------------------------------------------------------

class VendorProvenance(TypedDict):
    grounded: bool
    evidence_found_at: int


class AmountProvenance(TypedDict, total=False):
    """Amount provenance — evidence_found_at is added dynamically."""
    grounded: bool
    parsed_evidence: float | None
    delta: float | None
    evidence_found_at: int


class HasPoProvenance(TypedDict):
    grounded: bool
    po_pattern_found: bool | None


class InvoiceDateProvenance(TypedDict):
    grounded: bool
    evidence_found_at: int
    normalized_value: str | None
    normalized_evidence: str | None


class TaxAmountProvenance(TypedDict):
    grounded: bool
    evidence_found_at: int
    anchor_found: bool | None
    parsed_evidence: float | None
    delta: float | None


class ProvenanceReport(TypedDict, total=False):
    """Per-field provenance from verify_extraction().

    vendor, amount, has_po are always present (initialized by _default_provenance).
    invoice_date, tax_amount are present only when their validators run.
    """
    vendor: VendorProvenance
    amount: AmountProvenance
    has_po: HasPoProvenance
    invoice_date: InvoiceDateProvenance
    tax_amount: TaxAmountProvenance


# ---------------------------------------------------------------------------
# Structural validation (LLM output → shape check before verifier)
# ---------------------------------------------------------------------------

_REQUIRED_EXTRACTION_FIELDS: tuple[str, ...] = ("vendor", "amount", "has_po")


def validate_extraction_structure(
    parsed: dict,
) -> tuple[bool, list[str]]:
    """Validate LLM response has expected {field: {value, evidence}} shape.

    Returns (is_valid, issues).  Uses ``STRUCT_*`` codes distinct from verifier
    ``FailureCode`` literals.  Does NOT check evidence grounding or value types
    (that is the verifier's job).  Extra fields pass silently (forward-compatible).

    STRUCT_* codes and verifier FailureCodes are two distinct families.
    A given invocation produces either STRUCT_* codes (structural rejection)
    or verifier codes (evidence rejection), never both.
    """
    issues: list[str] = []
    if "_error" in parsed:
        return False, ["STRUCT_LLM_ERROR"]

    for field in _REQUIRED_EXTRACTION_FIELDS:
        if field not in parsed:
            issues.append(f"STRUCT_MISSING_{field.upper()}")
            continue
        entry = parsed[field]
        if not isinstance(entry, dict):
            issues.append(f"STRUCT_NOT_DICT_{field.upper()}")
            continue
        if "value" not in entry:
            issues.append(f"STRUCT_NO_VALUE_{field.upper()}")
        if "evidence" not in entry:
            issues.append(f"STRUCT_NO_EVIDENCE_{field.upper()}")
    return len(issues) == 0, issues
