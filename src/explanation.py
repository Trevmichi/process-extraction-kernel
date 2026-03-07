"""
src/explanation.py
Structured explanation module — transforms ParsedAuditLog into a typed
ExplanationReport with 6 optional decision-surface components.

Pure structural output.  No prose generation, no LLM calls, no UI changes.
Follows verifier_shadow.py pattern: frozen dataclass + to_dict().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .audit_parser import (
    AmountCandidatesEvent,
    ArithmeticCheckEvent,
    ExtractionEvent,
    MatchInputsEvent,
    ParsedAuditLog,
)
from .ontology import EXCEPTION_STATUSES, TERMINAL_STATUSES


# ===================================================================
# Outcome classification
# ===================================================================

_SUCCESS_STATUSES = frozenset({"APPROVED", "PAID", "CLOSED"})
_REJECTION_STATUSES = frozenset({"REJECTED", "ESCALATED", "BAD_EXTRACTION", "MISSING_DATA"})
_IN_PROGRESS_STATUSES = frozenset({"NEW", "DATA_EXTRACTED", "NEEDS_RETRY", "VALIDATED", "PENDING_INFO"})


def _classify_category(status: str) -> str:
    if status in EXCEPTION_STATUSES:
        return "exception"
    if status in _SUCCESS_STATUSES:
        return "success"
    if status in _REJECTION_STATUSES:
        return "rejection"
    if status in _IN_PROGRESS_STATUSES:
        return "in_progress"
    return "unknown"


@dataclass(frozen=True)
class OutcomeClassification:
    """Final disposition of the invoice processing run."""
    final_status: str
    is_terminal: bool
    is_exception: bool
    category: str

    def to_dict(self) -> dict:
        return {
            "final_status": self.final_status,
            "is_terminal": self.is_terminal,
            "is_exception": self.is_exception,
            "category": self.category,
        }


# ===================================================================
# Extraction explanation
# ===================================================================

@dataclass(frozen=True)
class ExtractionExplanation:
    """Summarises the last extraction attempt and verifier outcome."""
    variant: str
    valid: bool
    failure_codes: tuple[str, ...]
    status_before: str | None
    status_after: str | None
    field_results: dict | None
    extraction_count: int

    def to_dict(self) -> dict:
        return {
            "variant": self.variant,
            "valid": self.valid,
            "failure_codes": list(self.failure_codes),
            "status_before": self.status_before,
            "status_after": self.status_after,
            "field_results": self.field_results,
            "extraction_count": self.extraction_count,
        }


# ===================================================================
# Routing explanation
# ===================================================================

@dataclass(frozen=True)
class RoutingDecisionSummary:
    """One gateway routing decision."""
    gateway_id: str
    selected: str | None
    reason: str
    candidate_count: int
    matched_count: int
    is_exception_route: bool

    def to_dict(self) -> dict:
        return {
            "gateway_id": self.gateway_id,
            "selected": self.selected,
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "matched_count": self.matched_count,
            "is_exception_route": self.is_exception_route,
        }


@dataclass(frozen=True)
class RoutingExplanation:
    """All gateway routing decisions in chronological order."""
    decisions: tuple[RoutingDecisionSummary, ...]
    total_gateways: int

    def to_dict(self) -> dict:
        return {
            "decisions": [d.to_dict() for d in self.decisions],
            "total_gateways": self.total_gateways,
        }


# ===================================================================
# Match explanation
# ===================================================================

@dataclass(frozen=True)
class MatchExplanation:
    """3-way match resolution outcome."""
    match_result: str
    source_flag: str | None
    po_match_input: bool | None
    match_3_way_input: bool | None
    resolved_from: str

    def to_dict(self) -> dict:
        return {
            "match_result": self.match_result,
            "source_flag": self.source_flag,
            "po_match_input": self.po_match_input,
            "match_3_way_input": self.match_3_way_input,
            "resolved_from": self.resolved_from,
        }


# ===================================================================
# Exception explanation
# ===================================================================

@dataclass(frozen=True)
class ExceptionExplanation:
    """Why the invoice was routed to an exception station.

    ``expected_status`` is derived (not authoritative) — it is computed
    as ``f"EXCEPTION_{reason}"`` when that value exists in
    ``EXCEPTION_STATUSES``, otherwise ``"EXCEPTION_UNKNOWN"``.
    """
    reason: str
    triggering_gateway: str
    node: str
    expected_status: str

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "triggering_gateway": self.triggering_gateway,
            "node": self.node,
            "expected_status": self.expected_status,
        }


# ===================================================================
# Retry explanation
# ===================================================================

@dataclass(frozen=True)
class RetryAttemptSummary:
    """One CRITIC_RETRY attempt."""
    attempt: int
    valid: bool
    failure_codes: tuple[str, ...]
    status: str

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "valid": self.valid,
            "failure_codes": list(self.failure_codes),
            "status": self.status,
        }


@dataclass(frozen=True)
class RetryExplanation:
    """Critic retry attempt progression."""
    attempts: tuple[RetryAttemptSummary, ...]
    total_attempts: int
    final_valid: bool
    final_status: str

    def to_dict(self) -> dict:
        return {
            "attempts": [a.to_dict() for a in self.attempts],
            "total_attempts": self.total_attempts,
            "final_valid": self.final_valid,
            "final_status": self.final_status,
        }


# ===================================================================
# Amount explanation
# ===================================================================

@dataclass(frozen=True)
class AmountExplanation:
    """Amount candidate selection summary."""
    candidate_count: int
    selected: float | None
    winning_keyword: str | None
    ambiguous: bool

    def to_dict(self) -> dict:
        return {
            "candidate_count": self.candidate_count,
            "selected": self.selected,
            "winning_keyword": self.winning_keyword,
            "ambiguous": self.ambiguous,
        }


# ===================================================================
# Arithmetic explanation
# ===================================================================

@dataclass(frozen=True)
class ArithmeticExplanation:
    """Arithmetic consistency check summary."""
    checks_run: tuple[str, ...]
    passed: bool
    failure_codes: tuple[str, ...]
    total_sum_delta: float | None
    tax_rate_delta: float | None
    check_count: int

    def to_dict(self) -> dict:
        return {
            "checks_run": list(self.checks_run),
            "passed": self.passed,
            "failure_codes": list(self.failure_codes),
            "total_sum_delta": self.total_sum_delta,
            "tax_rate_delta": self.tax_rate_delta,
            "check_count": self.check_count,
        }


# ===================================================================
# Top-level report
# ===================================================================

@dataclass(frozen=True)
class ExplanationReport:
    """Structured explanation of an invoice processing run.

    Built from ``ParsedAuditLog`` via ``build_explanation()``.
    Each component is ``None`` when no relevant events exist.
    """
    schema_version: str
    extraction: ExtractionExplanation | None
    routing: RoutingExplanation | None
    match: MatchExplanation | None
    exception: ExceptionExplanation | None
    retry: RetryExplanation | None
    amount: AmountExplanation | None
    arithmetic: ArithmeticExplanation | None
    outcome: OutcomeClassification

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "extraction": self.extraction.to_dict() if self.extraction else None,
            "routing": self.routing.to_dict() if self.routing else None,
            "match": self.match.to_dict() if self.match else None,
            "exception": self.exception.to_dict() if self.exception else None,
            "retry": self.retry.to_dict() if self.retry else None,
            "amount": self.amount.to_dict() if self.amount else None,
            "arithmetic": self.arithmetic.to_dict() if self.arithmetic else None,
            "outcome": self.outcome.to_dict(),
        }


# ===================================================================
# Builder helpers
# ===================================================================

def _build_extraction(parsed: ParsedAuditLog) -> ExtractionExplanation | None:
    ext = parsed.last_extraction
    if ext is None:
        return None

    # Merge failure codes: prefer reasons if populated, else failure_codes
    if ext.reasons is not None:
        codes = ext.reasons
    elif ext.failure_codes is not None:
        codes = ext.failure_codes
    else:
        codes = ()

    vs = parsed.last_verifier_summary
    field_results: dict | None = None
    status_before: str | None = None
    status_after: str | None = None
    if vs is not None:
        field_results = {
            "vendor": vs.vendor,
            "amount": vs.amount,
            "has_po": vs.has_po,
        }
        status_before = vs.status_before
        status_after = vs.status_after

    return ExtractionExplanation(
        variant=ext.variant,
        valid=ext.valid,
        failure_codes=codes,
        status_before=status_before,
        status_after=status_after,
        field_results=field_results,
        extraction_count=len(parsed.extraction_events),
    )


def _build_routing(parsed: ParsedAuditLog) -> RoutingExplanation | None:
    if not parsed.route_decisions:
        return None

    summaries: list[RoutingDecisionSummary] = []
    for rd in parsed.route_decisions:
        matched = sum(1 for c in rd.candidates if c.get("matched") is True)
        summaries.append(RoutingDecisionSummary(
            gateway_id=rd.from_node,
            selected=rd.selected,
            reason=rd.reason,
            candidate_count=len(rd.candidates),
            matched_count=matched,
            is_exception_route=rd.reason in ("ambiguous_route", "no_route"),
        ))

    return RoutingExplanation(
        decisions=tuple(summaries),
        total_gateways=len(summaries),
    )


def _build_match(parsed: ParsedAuditLog) -> MatchExplanation | None:
    m = parsed.last_match
    if m is None:
        return None

    # Find last MatchInputsEvent
    mi: MatchInputsEvent | None = None
    for entry in reversed(parsed.entries):
        if isinstance(entry, MatchInputsEvent):
            mi = entry
            break

    po_match_input = mi.po_match if mi else None
    match_3_way_input = mi.match_3_way if mi else None

    # Determine resolved_from from source_flag
    if m.source_flag == "po_match":
        resolved_from = "po_match"
    elif m.source_flag == "match_3_way":
        resolved_from = "match_3_way"
    else:
        resolved_from = "none"

    return MatchExplanation(
        match_result=m.match_result,
        source_flag=m.source_flag,
        po_match_input=po_match_input,
        match_3_way_input=match_3_way_input,
        resolved_from=resolved_from,
    )


def _build_exception(parsed: ParsedAuditLog) -> ExceptionExplanation | None:
    exc = parsed.last_exception
    if exc is None:
        return None

    candidate = f"EXCEPTION_{exc.reason}"
    expected_status = candidate if candidate in EXCEPTION_STATUSES else "EXCEPTION_UNKNOWN"

    return ExceptionExplanation(
        reason=exc.reason,
        triggering_gateway=exc.gateway,
        node=exc.node,
        expected_status=expected_status,
    )


def _build_retry(parsed: ParsedAuditLog) -> RetryExplanation | None:
    if not parsed.critic_retries:
        return None

    attempts = tuple(
        RetryAttemptSummary(
            attempt=cr.attempt,
            valid=cr.valid,
            failure_codes=cr.failure_codes,
            status=cr.status,
        )
        for cr in parsed.critic_retries
    )

    last = parsed.critic_retries[-1]
    return RetryExplanation(
        attempts=attempts,
        total_attempts=len(attempts),
        final_valid=last.valid,
        final_status=last.status,
    )


def _build_amount(parsed: ParsedAuditLog) -> AmountExplanation | None:
    # AmountCandidatesEvent is not pre-categorized; scan entries
    ac: AmountCandidatesEvent | None = None
    for entry in reversed(parsed.entries):
        if isinstance(entry, AmountCandidatesEvent):
            ac = entry
            break

    if ac is None:
        return None

    return AmountExplanation(
        candidate_count=len(ac.candidates),
        selected=ac.selected,
        winning_keyword=ac.winning_keyword,
        ambiguous=len(ac.candidates) > 1,
    )


def _build_arithmetic(parsed: ParsedAuditLog) -> ArithmeticExplanation | None:
    ac = parsed.last_arithmetic_check
    if ac is None:
        return None

    total_sum_delta: float | None = None
    if ac.total_sum is not None:
        total_sum_delta = ac.total_sum.get("delta")

    tax_rate_delta: float | None = None
    if ac.tax_rate is not None:
        tax_rate_delta = ac.tax_rate.get("delta")

    return ArithmeticExplanation(
        checks_run=ac.checks_run,
        passed=ac.passed,
        failure_codes=ac.codes,
        total_sum_delta=total_sum_delta,
        tax_rate_delta=tax_rate_delta,
        check_count=len(ac.checks_run),
    )


def _infer_status(parsed: ParsedAuditLog) -> str:
    """Infer final status from audit events.

    Inference chain:
    1. Last exception → EXCEPTION_{reason}
    2. Last verifier summary → status_after
    3. Last extraction → status
    4. Fallback → "UNKNOWN"
    """
    exc = parsed.last_exception
    if exc is not None:
        candidate = f"EXCEPTION_{exc.reason}"
        return candidate if candidate in EXCEPTION_STATUSES else "EXCEPTION_UNKNOWN"

    vs = parsed.last_verifier_summary
    if vs is not None and vs.status_after:
        return vs.status_after

    ext = parsed.last_extraction
    if ext is not None and ext.status is not None:
        return ext.status

    return "UNKNOWN"


# ===================================================================
# Public API
# ===================================================================

def build_explanation(
    parsed: ParsedAuditLog,
    *,
    final_status: str | None = None,
) -> ExplanationReport:
    """Build a structured explanation from a parsed audit log.

    Parameters
    ----------
    parsed:
        Output of ``parse_audit_log()``.
    final_status:
        Explicit final status.  Preferred over inference when provided.
        If ``None``, status is inferred from audit events.

    Returns
    -------
    ExplanationReport
        Frozen dataclass with 6 optional components + outcome classification.
    """
    status = final_status if final_status is not None else _infer_status(parsed)

    outcome = OutcomeClassification(
        final_status=status,
        is_terminal=status in TERMINAL_STATUSES,
        is_exception=status in EXCEPTION_STATUSES,
        category=_classify_category(status),
    )

    return ExplanationReport(
        schema_version="explanation_v1",
        extraction=_build_extraction(parsed),
        routing=_build_routing(parsed),
        match=_build_match(parsed),
        exception=_build_exception(parsed),
        retry=_build_retry(parsed),
        amount=_build_amount(parsed),
        arithmetic=_build_arithmetic(parsed),
        outcome=outcome,
    )
