"""
src/audit_parser.py
Canonical single-pass parser for APState audit_log entries.

Produces typed, frozen dataclasses for all 10 JSON event families,
plain-text route steps, and unknown entries.  This module does NOT
modify or replace ``ui_audit.py`` — it sits above it as a structured
layer for explanation and analysis code.

No runtime schema validation.  Schemas in ``schema/`` inform the
dataclass shapes; ``jsonschema`` is not a runtime dependency.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Union


# ---------------------------------------------------------------------------
# Plain-text regex
# ---------------------------------------------------------------------------

_ROUTE_STEP_RE = re.compile(
    r"^Executed\s+(\S+)"           # intent (e.g. APPROVE)
    r"(?:\s+\[([^\]]+)\])?"        # optional [actor]
    r"\s+at\s+(\S+)$"              # node_id
)


# ===================================================================
# Typed event dataclasses — schema-backed (6)
# ===================================================================

@dataclass(frozen=True)
class RouteDecisionEvent:
    """Gateway routing decision (audit_event_route_decision_v1)."""
    event: str
    from_node: str
    candidates: tuple[dict, ...]
    selected: str | None
    reason: str


@dataclass(frozen=True)
class ExtractionEvent:
    """ENTER_RECORD extraction result (audit_event_extraction_v1).

    Has 3 variants with different key sets:
    - LLM error: reasons=("LLM_ERROR",), failure_codes=None
    - Structural failure: reasons=None, failure_codes=(STRUCT_*,...), status="BAD_EXTRACTION"
    - Verifier result: reasons=(...), failure_codes=None
    """
    event: str
    node: str
    valid: bool
    reasons: tuple[str, ...] | None
    failure_codes: tuple[str, ...] | None
    status: str | None

    @property
    def variant(self) -> str:
        """Return 'llm_error', 'structural', or 'verifier'."""
        if self.reasons is not None and "LLM_ERROR" in self.reasons:
            return "llm_error"
        if self.failure_codes is not None:
            return "structural"
        return "verifier"


@dataclass(frozen=True)
class ExceptionStationEvent:
    """Exception station routing (audit_event_exception_station_v1)."""
    event: str
    node: str
    reason: str
    gateway: str


@dataclass(frozen=True)
class MatchResultSetEvent:
    """3-way match result (audit_event_match_result_set_v1)."""
    event: str
    node: str
    match_result: str
    source_flag: str | None


@dataclass(frozen=True)
class VerifierSummaryEvent:
    """Per-field grounding summary (audit_event_verifier_summary_v1).

    vendor, amount, has_po are kept as plain dicts — no sub-dataclasses.
    """
    event: str
    valid: bool
    failure_codes: tuple[str, ...]
    status_before: str
    status_after: str
    vendor: dict
    amount: dict
    has_po: dict


@dataclass(frozen=True)
class CriticRetryEvent:
    """CRITIC_RETRY execution result (audit_event_critic_retry_v1)."""
    event: str
    node: str
    attempt: int
    valid: bool
    failure_codes: tuple[str, ...]
    status: str


# ===================================================================
# Typed event dataclasses — non-schema (4)
# ===================================================================

@dataclass(frozen=True)
class RouteRecordEvent:
    """Full RouteRecord wrapper (route_record_v1 already schema-backed)."""
    event: str
    route_record: dict


@dataclass(frozen=True)
class MatchInputsEvent:
    """Raw match inputs before resolution."""
    event: str
    node: str
    po_match: bool | None
    match_3_way: bool | None


@dataclass(frozen=True)
class AmountCandidatesEvent:
    """All money-like candidates found in raw text."""
    event: str
    candidates: tuple[dict, ...]
    selected: float | None
    winning_keyword: str | None


@dataclass(frozen=True)
class SequentialDispatchEvent:
    """Sequential dispatch chain."""
    event: str
    node: str
    chain: tuple[str, ...]


# ===================================================================
# Non-JSON entry types
# ===================================================================

@dataclass(frozen=True)
class RouteStepEntry:
    """Parsed from plain text ``"Executed {intent} [{actor}] at {node}"``."""
    raw: str
    intent: str
    node_id: str
    actor: str | None


@dataclass(frozen=True)
class PlainTextEntry:
    """Any plain-text audit entry not matching known patterns."""
    raw: str


@dataclass(frozen=True)
class UnknownJsonEntry:
    """JSON dict with unrecognized or missing ``event`` key."""
    raw: dict
    event: str | None


# ===================================================================
# Union type
# ===================================================================

AuditEntry = Union[
    RouteDecisionEvent,
    ExtractionEvent,
    ExceptionStationEvent,
    MatchResultSetEvent,
    VerifierSummaryEvent,
    CriticRetryEvent,
    RouteRecordEvent,
    MatchInputsEvent,
    AmountCandidatesEvent,
    SequentialDispatchEvent,
    RouteStepEntry,
    PlainTextEntry,
    UnknownJsonEntry,
]


# ===================================================================
# ParsedAuditLog
# ===================================================================

@dataclass(frozen=True)
class ParsedAuditLog:
    """Immutable structured view of an audit_log list."""

    entries: tuple[AuditEntry, ...]

    # Category accessors (pre-computed)
    route_decisions: tuple[RouteDecisionEvent, ...] = ()
    extraction_events: tuple[ExtractionEvent, ...] = ()
    verifier_summaries: tuple[VerifierSummaryEvent, ...] = ()
    exception_events: tuple[ExceptionStationEvent, ...] = ()
    match_events: tuple[MatchResultSetEvent, ...] = ()
    critic_retries: tuple[CriticRetryEvent, ...] = ()
    route_records: tuple[RouteRecordEvent, ...] = ()
    plain_text: tuple[PlainTextEntry, ...] = ()
    unknown_json: tuple[UnknownJsonEntry, ...] = ()

    # --- Convenience "last" accessors ---

    @property
    def last_exception(self) -> ExceptionStationEvent | None:
        return self.exception_events[-1] if self.exception_events else None

    @property
    def last_extraction(self) -> ExtractionEvent | None:
        return self.extraction_events[-1] if self.extraction_events else None

    @property
    def last_match(self) -> MatchResultSetEvent | None:
        return self.match_events[-1] if self.match_events else None

    @property
    def last_verifier_summary(self) -> VerifierSummaryEvent | None:
        return self.verifier_summaries[-1] if self.verifier_summaries else None


# ===================================================================
# Factory functions (defensive, never raise)
# ===================================================================

def _make_route_decision(obj: dict) -> RouteDecisionEvent:
    return RouteDecisionEvent(
        event="route_decision",
        from_node=obj.get("from_node", ""),
        candidates=tuple(obj.get("candidates") or ()),
        selected=obj.get("selected"),
        reason=obj.get("reason", ""),
    )


def _make_extraction(obj: dict) -> ExtractionEvent:
    return ExtractionEvent(
        event="extraction",
        node=obj.get("node", ""),
        valid=obj.get("valid", False),
        reasons=tuple(obj["reasons"]) if "reasons" in obj else None,
        failure_codes=tuple(obj["failure_codes"]) if "failure_codes" in obj else None,
        status=obj.get("status"),
    )


def _make_exception_station(obj: dict) -> ExceptionStationEvent:
    return ExceptionStationEvent(
        event="exception_station",
        node=obj.get("node", ""),
        reason=obj.get("reason", ""),
        gateway=obj.get("gateway", ""),
    )


def _make_match_result_set(obj: dict) -> MatchResultSetEvent:
    return MatchResultSetEvent(
        event="match_result_set",
        node=obj.get("node", ""),
        match_result=obj.get("match_result", ""),
        source_flag=obj.get("source_flag"),
    )


def _make_verifier_summary(obj: dict) -> VerifierSummaryEvent:
    return VerifierSummaryEvent(
        event="verifier_summary",
        valid=obj.get("valid", False),
        failure_codes=tuple(obj.get("failure_codes") or ()),
        status_before=obj.get("status_before", ""),
        status_after=obj.get("status_after", ""),
        vendor=obj.get("vendor") or {},
        amount=obj.get("amount") or {},
        has_po=obj.get("has_po") or {},
    )


def _make_critic_retry(obj: dict) -> CriticRetryEvent:
    return CriticRetryEvent(
        event="critic_retry_executed",
        node=obj.get("node", ""),
        attempt=obj.get("attempt", 0),
        valid=obj.get("valid", False),
        failure_codes=tuple(obj.get("failure_codes") or ()),
        status=obj.get("status", ""),
    )


def _make_route_record(obj: dict) -> RouteRecordEvent:
    return RouteRecordEvent(
        event="route_record",
        route_record=obj.get("route_record") or {},
    )


def _make_match_inputs(obj: dict) -> MatchInputsEvent:
    return MatchInputsEvent(
        event="match_inputs",
        node=obj.get("node", ""),
        po_match=obj.get("po_match"),
        match_3_way=obj.get("match_3_way"),
    )


def _make_amount_candidates(obj: dict) -> AmountCandidatesEvent:
    return AmountCandidatesEvent(
        event="amount_candidates",
        candidates=tuple(obj.get("candidates") or ()),
        selected=obj.get("selected"),
        winning_keyword=obj.get("winning_keyword"),
    )


def _make_sequential_dispatch(obj: dict) -> SequentialDispatchEvent:
    return SequentialDispatchEvent(
        event="sequential_dispatch",
        node=obj.get("node", ""),
        chain=tuple(obj.get("chain") or ()),
    )


# ===================================================================
# Dispatch table
# ===================================================================

_DISPATCH: dict[str, object] = {
    "route_decision": _make_route_decision,
    "extraction": _make_extraction,
    "exception_station": _make_exception_station,
    "match_result_set": _make_match_result_set,
    "verifier_summary": _make_verifier_summary,
    "critic_retry_executed": _make_critic_retry,
    "route_record": _make_route_record,
    "match_inputs": _make_match_inputs,
    "amount_candidates": _make_amount_candidates,
    "sequential_dispatch": _make_sequential_dispatch,
}


# ===================================================================
# Plain-text classification
# ===================================================================

def _classify_plain_text(entry: str) -> AuditEntry:
    m = _ROUTE_STEP_RE.match(entry)
    if m:
        return RouteStepEntry(
            raw=entry,
            intent=m.group(1),
            node_id=m.group(3),
            actor=m.group(2),
        )
    return PlainTextEntry(raw=entry)


# ===================================================================
# Public API
# ===================================================================

def parse_audit_log(audit_log: list[str]) -> ParsedAuditLog:
    """Parse an audit_log list into a typed, immutable structure.

    Single forward pass.  Defensive — never raises on malformed input.
    """
    entries: list[AuditEntry] = []

    # Category accumulators
    route_decisions: list[RouteDecisionEvent] = []
    extraction_events: list[ExtractionEvent] = []
    verifier_summaries: list[VerifierSummaryEvent] = []
    exception_events: list[ExceptionStationEvent] = []
    match_events: list[MatchResultSetEvent] = []
    critic_retries: list[CriticRetryEvent] = []
    route_records: list[RouteRecordEvent] = []
    plain_text: list[PlainTextEntry] = []
    unknown_json: list[UnknownJsonEntry] = []

    for entry in audit_log:
        # --- Try to parse as dict ---
        obj: dict | None = None
        if isinstance(entry, dict):
            obj = entry
        elif isinstance(entry, str):
            try:
                parsed = json.loads(entry)
                if isinstance(parsed, dict):
                    obj = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        if obj is not None:
            event_name = obj.get("event")
            factory = _DISPATCH.get(event_name) if event_name else None
            if factory is not None:
                typed = factory(obj)
            else:
                typed = UnknownJsonEntry(raw=obj, event=event_name)

            entries.append(typed)

            # Route to category accumulator
            if isinstance(typed, RouteDecisionEvent):
                route_decisions.append(typed)
            elif isinstance(typed, ExtractionEvent):
                extraction_events.append(typed)
            elif isinstance(typed, VerifierSummaryEvent):
                verifier_summaries.append(typed)
            elif isinstance(typed, ExceptionStationEvent):
                exception_events.append(typed)
            elif isinstance(typed, MatchResultSetEvent):
                match_events.append(typed)
            elif isinstance(typed, CriticRetryEvent):
                critic_retries.append(typed)
            elif isinstance(typed, RouteRecordEvent):
                route_records.append(typed)
            elif isinstance(typed, UnknownJsonEntry):
                unknown_json.append(typed)
            continue

        # --- Plain text (or non-string/non-dict: skip) ---
        if isinstance(entry, str):
            typed = _classify_plain_text(entry)
            entries.append(typed)
            if isinstance(typed, PlainTextEntry):
                plain_text.append(typed)
            continue

        # Non-string, non-dict: silently skip

    return ParsedAuditLog(
        entries=tuple(entries),
        route_decisions=tuple(route_decisions),
        extraction_events=tuple(extraction_events),
        verifier_summaries=tuple(verifier_summaries),
        exception_events=tuple(exception_events),
        match_events=tuple(match_events),
        critic_retries=tuple(critic_retries),
        route_records=tuple(route_records),
        plain_text=tuple(plain_text),
        unknown_json=tuple(unknown_json),
    )
