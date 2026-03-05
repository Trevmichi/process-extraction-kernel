"""
nodes.py
Generic node executor and LangGraph node factory for the AP process agent.

Each process node in the compiled graph is backed by a handler produced by
`create_node_handler`.  The handler receives the full APState, delegates to
`execute_node` for the actual simulation work, and returns a partial state
dict that LangGraph merges into the shared state.

Smart nodes (ENTER_RECORD, VALIDATE_FIELDS) call the local Ollama LLM to
perform data extraction / validation on raw invoice text.  All other nodes
use fast deterministic logic.

Evidence-backed verifier
------------------------
ENTER_RECORD always runs the deterministic evidence verifier after LLM
extraction.  The LLM must return ``{field: {value, evidence}, ...}``
where evidence is a verbatim substring of the raw text.  The verifier
cross-checks grounding, amount math, and PO patterns.

On failure, ``status`` is set to ``"BAD_EXTRACTION"`` and the graph
routes to the rejection node.

Set ``ALLOW_UNVERIFIED_EXTRACTION=true`` to still write extracted values
to state even when verification fails (for debugging).  Status still
becomes ``"BAD_EXTRACTION"`` and routing still goes to reject.
"""
from __future__ import annotations

import json
import os
from typing import Callable

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from .state import APState
from ..verifier import (
    verify_extraction,
    MONEY_RE, CURRENCY_RE, AMOUNT_KEYWORDS, KEYWORD_WINDOW, normalize_text,
)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def _allow_unverified() -> bool:
    """When True, write extracted values to state even on verifier failure (debug only)."""
    return os.environ.get("ALLOW_UNVERIFIED_EXTRACTION", "").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Module-level LLM instance (shared; avoids repeated construction overhead)
# ---------------------------------------------------------------------------
_llm = ChatOllama(model="gemma3:12b", temperature=0.0, format="json")


# ---------------------------------------------------------------------------
# Intent → human-readable label
# ---------------------------------------------------------------------------
def _intent_label(node_data: dict) -> str:
    """Extract the most descriptive label from a node dict."""
    action   = node_data.get("action") or {}
    decision = node_data.get("decision") or {}
    return (
        action.get("type")
        or decision.get("type")
        or node_data.get("kind", "UNKNOWN")
    )


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
def _call_llm_json(prompt: str) -> dict:
    """
    Invoke the local LLM and return a parsed JSON dict.

    Strips markdown code fences if the model wraps the response in them.
    Returns ``{"_error": <message>}`` on any failure so callers can degrade
    gracefully without raising.
    """
    try:
        response = _llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, str):
            raw = content.strip()
        else:
            raw_parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    raw_parts.append(item)
                else:
                    raw_parts.append(json.dumps(item))
            raw = "".join(raw_parts).strip()

        # Strip ```json ... ``` or ``` ... ``` fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)
    except Exception as exc:
        return {"_error": str(exc)}




# ---------------------------------------------------------------------------
# Prompt builders (single source of truth)
# ---------------------------------------------------------------------------

def build_enter_record_prompt(raw_text: str) -> str:
    """Build the ENTER_RECORD extraction prompt for a given invoice text.

    This is the single source of truth for the extraction prompt template.
    Used by execute_node (ENTER_RECORD branch) and by eval_variance.py.
    """
    return f"""You are a precise data extractor. Read the following invoice/PO text and output a JSON object.
For EACH field, return a nested object with "value" (the canonical value) and "evidence"
(the EXACT verbatim substring from the text that supports your answer — copy it character for character).

Schema:
{{
  "vendor":  {{"value": "<string>",  "evidence": "<exact substring>"}},
  "amount":  {{"value": <float>,     "evidence": "<exact substring>"}},
  "has_po":  {{"value": <boolean>,   "evidence": "<exact substring>"}}
}}

Rules:
- "amount.value": float with no currency symbols or commas (e.g. 835.45 not $835.45)
- "evidence" MUST be copied verbatim from the text — do NOT paraphrase or summarize
- If a field cannot be found, set value to null and evidence to ""

Text:
{raw_text}"""


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------
def execute_node(state: APState, node_data: dict,
                 outgoing_edges: list[dict] | None = None) -> dict:
    """
    Simulate an agent performing work at *node_data*.

    Smart nodes (ENTER_RECORD, VALIDATE_FIELDS) call the local Ollama LLM.
    All other nodes use deterministic logic.

    Returns a partial state dict suitable for LangGraph's merge.
    """
    node_id = node_data["id"]
    intent  = _intent_label(node_data)
    actor   = (node_data.get("action") or {}).get("actor_id", "")
    actor_tag = f" [{actor}]" if actor else ""

    updates: dict = {"current_node": node_id}

    # Track gateway routing context for exception stations
    if node_data.get("kind") == "gateway":
        updates["last_gateway"] = node_id
        # Emit structured route_decision audit event
        if outgoing_edges:
            from .router import analyze_routing
            result = analyze_routing(state, outgoing_edges)
            updates.setdefault("audit_log", []).append(json.dumps({
                "event": "route_decision",
                "from_node": node_id,
                "candidates": result.candidates,
                "selected": result.selected,
                "reason": result.reason,
            }))

    # ---- Smart node: evidence-backed data extraction -------------------------
    if intent == "ENTER_RECORD":
        raw_text = state.get("raw_text", "")
        prompt = build_enter_record_prompt(raw_text)
        parsed = _call_llm_json(prompt)

        # Always write extraction payload (even on LLM error)
        updates["extraction"] = parsed

        if "_error" in parsed:
            updates["provenance"] = {}
            updates["status"] = "BAD_EXTRACTION"
            updates["failure_codes"] = ["LLM_ERROR"]
            updates["audit_log"] = [
                json.dumps({"node": "ENTER_RECORD", "event": "extraction",
                            "valid": False, "reasons": ["LLM_ERROR"]})
            ]
        else:
            # Run deterministic evidence verifier
            valid, codes, prov = verify_extraction(raw_text, parsed)
            updates["provenance"] = prov

            # Build per-field evidence presence flags
            _vendor_ev = (parsed.get("vendor") or {}).get("evidence") or ""
            _amount_ev = (parsed.get("amount") or {}).get("evidence") or ""
            _haspo_ev = (parsed.get("has_po") or {}).get("evidence") or ""

            status_before = state.get("status", "NEW")
            _retry_count = state.get("retry_count", 0)
            if valid:
                status_after = "DATA_EXTRACTED"
            else:
                status_after = "NEEDS_RETRY" if _retry_count == 0 else "BAD_EXTRACTION"

            updates["audit_log"] = [
                json.dumps({"node": "ENTER_RECORD", "event": "extraction",
                            "valid": valid, "reasons": list(codes)}),
                json.dumps({"event": "verifier_summary", "valid": valid,
                            "failure_codes": list(codes),
                            "status_before": status_before,
                            "status_after": status_after,
                            "vendor": {"value": parsed.get("vendor", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("MISSING_VENDOR", "VENDOR_EVIDENCE_MISMATCH",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_vendor_ev.strip())},
                            "amount": {"value": parsed.get("amount", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("AMOUNT_MISMATCH", "AMBIGUOUS_AMOUNT_EVIDENCE",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_amount_ev.strip()),
                                       "parsed_evidence": prov.get("amount", {}).get("parsed_evidence"),
                                       "delta": prov.get("amount", {}).get("delta")},
                            "has_po": {"value": parsed.get("has_po", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("PO_PATTERN_MISSING", "MISSING_EVIDENCE",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_haspo_ev.strip())}}),
            ]

            # Emit amount_candidates for audit: all money-like values in raw text
            _norm = normalize_text(raw_text)
            _cleaned = CURRENCY_RE.sub("", _norm)
            _amt_candidates = []
            _winning_keyword = None
            for _m in MONEY_RE.finditer(_cleaned):
                _raw_num = _m.group()
                _parsed_num = _raw_num.replace(",", "")
                if not _parsed_num or _parsed_num == ".":
                    continue
                try:
                    _val = float(_parsed_num)
                except ValueError:
                    continue
                # Check keyword window for this candidate
                _start = max(0, _m.start() - KEYWORD_WINDOW)
                _window = _cleaned[_start:_m.start()]
                _kw_hit = next((kw for kw in AMOUNT_KEYWORDS if kw in _window), None)
                _amt_candidates.append({
                    "raw": _raw_num, "parsed": _val, "keyword": _kw_hit,
                })
                if _kw_hit and _val == prov.get("amount", {}).get("parsed_evidence"):
                    _winning_keyword = _kw_hit

            updates["audit_log"].append(json.dumps({
                "event": "amount_candidates",
                "candidates": _amt_candidates,
                "selected": prov.get("amount", {}).get("parsed_evidence"),
                "winning_keyword": _winning_keyword,
            }))

            if valid:
                # Map nested values to core state fields
                updates["vendor"] = str(parsed["vendor"]["value"])
                updates["amount"] = float(parsed["amount"]["value"])
                updates["has_po"] = bool(parsed["has_po"]["value"])
                updates["status"] = "DATA_EXTRACTED"
                updates["failure_codes"] = []
            else:
                # Verification failed — use NEEDS_RETRY on first attempt,
                # BAD_EXTRACTION if already retried (avoids compound DSL conditions)
                retry_count = state.get("retry_count", 0)
                updates["status"] = "NEEDS_RETRY" if retry_count == 0 else "BAD_EXTRACTION"
                updates["failure_codes"] = list(codes)
                if _allow_unverified():
                    # Debug mode: still write values (status stays BAD_EXTRACTION)
                    v = parsed.get("vendor", {})
                    a = parsed.get("amount", {})
                    p = parsed.get("has_po", {})
                    if isinstance(v, dict) and v.get("value"):
                        updates["vendor"] = str(v["value"])
                    if isinstance(a, dict) and isinstance(a.get("value"), (int, float)):
                        updates["amount"] = float(a["value"])
                    if isinstance(p, dict) and isinstance(p.get("value"), bool):
                        updates["has_po"] = p["value"]

    # ---- Smart node: forensic critic retry -----------------------------------
    elif intent == "CRITIC_RETRY":
        raw_text = state.get("raw_text", "")
        failure_codes = state.get("failure_codes", [])
        prev_extraction = state.get("extraction", {})
        retry_count = state.get("retry_count", 0)

        updates["retry_count"] = retry_count + 1

        prompt = f"""You are a forensic extraction critic. A previous extraction attempt failed verification.

FAILURE CODES: {failure_codes}
PREVIOUS EXTRACTION: {json.dumps(prev_extraction, indent=2)}

Re-read the invoice text below. For each failed field, find the correct value and its
verbatim evidence. Return the corrected extraction as a complete JSON object using this
exact schema:

{{
  "vendor":  {{"value": "<string>",  "evidence": "<exact substring>"}},
  "amount":  {{"value": <float>,     "evidence": "<exact substring>"}},
  "has_po":  {{"value": <boolean>,   "evidence": "<exact substring>"}}
}}

Rules:
- "amount.value": float with no currency symbols or commas (e.g. 835.45 not $835.45)
- "evidence" MUST be copied verbatim from the text — do NOT paraphrase or summarize
- If you cannot fix a field, keep the original value and evidence

Text:
{raw_text}"""
        parsed = _call_llm_json(prompt)
        updates["extraction"] = parsed

        if "_error" in parsed:
            updates["provenance"] = {}
            updates["status"] = "BAD_EXTRACTION"
            updates["failure_codes"] = ["LLM_ERROR"]
            updates["audit_log"] = [
                json.dumps({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                            "attempt": retry_count + 1, "valid": False,
                            "failure_codes": ["LLM_ERROR"], "status": "BAD_EXTRACTION"})
            ]
        else:
            valid, codes, prov = verify_extraction(raw_text, parsed)
            updates["provenance"] = prov

            cr_status = "DATA_EXTRACTED" if valid else "BAD_EXTRACTION"
            updates["failure_codes"] = [] if valid else list(codes)

            # Per-field evidence presence flags (mirrors ENTER_RECORD)
            _vendor_ev = (parsed.get("vendor") or {}).get("evidence") or ""
            _amount_ev = (parsed.get("amount") or {}).get("evidence") or ""
            _haspo_ev = (parsed.get("has_po") or {}).get("evidence") or ""

            updates["audit_log"] = [
                # Critic-specific event
                json.dumps({"event": "critic_retry_executed", "node": "CRITIC_RETRY",
                            "attempt": retry_count + 1, "valid": valid,
                            "failure_codes": list(codes), "status": cr_status}),
                # verifier_summary (same structure as ENTER_RECORD)
                json.dumps({"event": "verifier_summary", "valid": valid,
                            "failure_codes": list(codes),
                            "status_before": state.get("status", ""),
                            "status_after": cr_status,
                            "vendor": {"value": parsed.get("vendor", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("MISSING_VENDOR", "VENDOR_EVIDENCE_MISMATCH",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_vendor_ev.strip())},
                            "amount": {"value": parsed.get("amount", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("AMOUNT_MISMATCH", "AMBIGUOUS_AMOUNT_EVIDENCE",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_amount_ev.strip()),
                                       "parsed_evidence": prov.get("amount", {}).get("parsed_evidence"),
                                       "delta": prov.get("amount", {}).get("delta")},
                            "has_po": {"value": parsed.get("has_po", {}).get("value"),
                                       "ok": not any(c in codes for c in
                                           ("PO_PATTERN_MISSING", "MISSING_EVIDENCE",
                                            "EVIDENCE_NOT_FOUND")),
                                       "has_evidence": bool(_haspo_ev.strip())}}),
            ]

            # amount_candidates (same structure as ENTER_RECORD)
            _norm = normalize_text(raw_text)
            _cleaned = CURRENCY_RE.sub("", _norm)
            _amt_candidates = []
            _winning_keyword = None
            for _m in MONEY_RE.finditer(_cleaned):
                _raw_num = _m.group()
                _parsed_num = _raw_num.replace(",", "")
                if not _parsed_num or _parsed_num == ".":
                    continue
                try:
                    _val = float(_parsed_num)
                except ValueError:
                    continue
                _start = max(0, _m.start() - KEYWORD_WINDOW)
                _window = _cleaned[_start:_m.start()]
                _kw_hit = next((kw for kw in AMOUNT_KEYWORDS if kw in _window), None)
                _amt_candidates.append({
                    "raw": _raw_num, "parsed": _val, "keyword": _kw_hit,
                })
                if _kw_hit and _val == prov.get("amount", {}).get("parsed_evidence"):
                    _winning_keyword = _kw_hit

            updates["audit_log"].append(json.dumps({
                "event": "amount_candidates",
                "candidates": _amt_candidates,
                "selected": prov.get("amount", {}).get("parsed_evidence"),
                "winning_keyword": _winning_keyword,
            }))

            if valid:
                updates["vendor"] = str(parsed["vendor"]["value"])
                updates["amount"] = float(parsed["amount"]["value"])
                updates["has_po"] = bool(parsed["has_po"]["value"])
                updates["status"] = "DATA_EXTRACTED"
            else:
                updates["status"] = "BAD_EXTRACTION"
                if _allow_unverified():
                    v = parsed.get("vendor", {})
                    a = parsed.get("amount", {})
                    p = parsed.get("has_po", {})
                    if isinstance(v, dict) and v.get("value"):
                        updates["vendor"] = str(v["value"])
                    if isinstance(a, dict) and isinstance(a.get("value"), (int, float)):
                        updates["amount"] = float(a["value"])
                    if isinstance(p, dict) and isinstance(p.get("value"), bool):
                        updates["has_po"] = p["value"]

    # ---- Smart node: field validation ---------------------------------------
    elif intent == "VALIDATE_FIELDS":
        prompt = (
            "You are a validator. Look at this data: "
            f"Vendor: {state['vendor']}, Amount: {state['amount']}, "
            f"PO: {state['has_po']}. "
            'If all fields have valid data (not empty/null), output JSON {"is_valid": true}. '
            'Else output {"is_valid": false}.'
        )
        parsed = _call_llm_json(prompt)
        updates["audit_log"] = [f"Validation result: {parsed}"]
        if "_error" not in parsed:
            updates["status"] = "VALIDATED" if parsed.get("is_valid") else "MISSING_DATA"

    # ---- Exception station: ROUTE_FOR_REVIEW --------------------------------
    elif intent == "ROUTE_FOR_REVIEW":
        reason = ((node_data.get("action") or {}).get("extra") or {}).get("reason", "UNKNOWN")
        canonical = (node_data.get("meta") or {}).get("canonical_key", node_id)
        updates["audit_log"] = [
            json.dumps({
                "node": canonical,
                "event": "exception_station",
                "reason": reason,
                "gateway": state.get("last_gateway", "?"),
            })
        ]
        updates["status"] = f"EXCEPTION_{reason}"

    # ---- Standard nodes: deterministic pass-through -------------------------
    else:
        updates.setdefault("audit_log", []).append(
            f"Executed {intent}{actor_tag} at {node_id}"
        )
        if intent == "APPROVE":
            updates["status"] = "APPROVED"
        elif intent in ("REJECT", "REJECT_INVOICE"):
            updates["status"] = "REJECTED"
        elif intent == "ESCALATE_TO_DIRECTOR":
            updates["status"] = "ESCALATED"
        elif intent == "MANUAL_REVIEW_NO_PO":
            updates["audit_log"] = [
                f"Executed {intent}{actor_tag} at {node_id}",
                json.dumps({
                    "event": "exception_station",
                    "node": node_id,
                    "reason": "NO_PO",
                    "gateway": state.get("last_gateway", "?"),
                }),
            ]
            updates["status"] = "EXCEPTION_NO_PO"
        elif intent == "MANUAL_REVIEW_MATCH_FAILED":
            updates["audit_log"] = [
                f"Executed {intent}{actor_tag} at {node_id}",
                json.dumps({
                    "event": "exception_station",
                    "node": node_id,
                    "reason": "MATCH_FAILED",
                    "gateway": state.get("last_gateway", "?"),
                }),
            ]
            updates["status"] = "EXCEPTION_MATCH_FAILED"
        elif intent == "MANUAL_REVIEW_UNMODELED_GATE":
            updates["audit_log"] = [
                f"Executed {intent}{actor_tag} at {node_id}",
                json.dumps({
                    "event": "exception_station",
                    "node": node_id,
                    "reason": "UNMODELED_GATE",
                    "gateway": state.get("last_gateway", "?"),
                }),
            ]
            updates["status"] = "EXCEPTION_UNMODELED"
        elif intent == "SEQUENTIAL_DISPATCH":
            chain = ((node_data.get("action") or {}).get("extra") or {}).get("chain", [])
            updates["audit_log"] = [
                json.dumps({
                    "node": node_id,
                    "event": "sequential_dispatch",
                    "chain": chain,
                }),
            ]
        elif intent == "MATCH_3_WAY":
            # Deterministic resolver: po_match > match_3_way > None
            source_flag: str | None = None
            flag_value = None
            if "po_match" in state and state.get("po_match") is not None:
                source_flag = "po_match"
                flag_value = state["po_match"]
            elif "match_3_way" in state and state.get("match_3_way") is not None:
                source_flag = "match_3_way"
                flag_value = state["match_3_way"]

            if flag_value is True:
                match_result = "MATCH"
            elif flag_value is False:
                match_result = "NO_MATCH"
            else:
                match_result = "UNKNOWN"

            updates["match_3_way"] = bool(flag_value) if flag_value is not None else False
            updates["match_result"] = match_result
            updates["audit_log"] = [
                json.dumps({
                    "node": "MATCH_3_WAY",
                    "event": "match_inputs",
                    "po_match": state.get("po_match"),
                    "match_3_way": state.get("match_3_way"),
                }),
                json.dumps({
                    "node": "MATCH_3_WAY",
                    "event": "match_result_set",
                    "match_result": match_result,
                    "source_flag": source_flag,
                }),
            ]
        elif intent == "EXECUTE_PAYMENT":
            updates["status"] = "PAID"
        elif intent == "UPDATE_STATUS":
            if state.get("status") not in ("APPROVED", "PAID", "REJECTED"):
                updates["status"] = "CLOSED"
        elif intent == "REQUEST_CLARIFICATION":
            if state.get("status") == "NEW":
                updates["status"] = "PENDING_INFO"

    return updates


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_node_handler(
    node_id: str,
    node_data: dict,
    outgoing_edges: list[dict] | None = None,
) -> Callable[[APState], dict]:
    """
    Return a LangGraph-compatible callable for *node_id*.

    The returned function is named ``node_<id>`` so it appears legibly
    in LangGraph's debug output and Mermaid diagram exports.

    Parameters
    ----------
    outgoing_edges : passed to ``execute_node`` so gateway nodes can emit
                     structured ``route_decision`` audit events.
    """
    def handler(state: APState) -> dict:
        return execute_node(state, node_data, outgoing_edges)

    handler.__name__ = f"node_{node_id}"
    return handler
