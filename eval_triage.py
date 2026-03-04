"""
eval_triage.py
Deterministic invariant checks and triage autopilot for the AP eval harness.

All functions are pure Python — no LLM calls.  They run during the standard
eval loop to flag suspicious passes (accidental correctness) and generate
actionable remediation plans for failures.

Functions
---------
compute_invariant_signals
    Four deterministic rules that flag extraction anomalies.

generate_action_plan
    Maps failure bucket + signals to owner / recommended next steps / files.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Known buyer entities (casefolded).  If the extracted vendor matches one of
# these, the LLM probably extracted the buyer instead of the seller.
# ---------------------------------------------------------------------------
_BUYER_ENTITIES: frozenset[str] = frozenset({
    "northriver",
    "northriver corp",
    "acme corp",
})

# Non-money patterns that overlap with numeric amounts
_PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")
_INVOICE_ID_RE = re.compile(r"\b(INV|NR|TG|GLC|APX)-\d+\b", re.IGNORECASE)

# Bill-to / Ship-to header patterns
_BILL_SHIP_RE = re.compile(r"^\s*(bill\s+to|ship\s+to)\s*:?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Invariant signals
# ---------------------------------------------------------------------------

def compute_invariant_signals(
    raw_text: str,
    extraction: dict,
    amount_candidates_event: dict | None,
) -> list[str]:
    """Return a list of deterministic anomaly flags for one invoice.

    Parameters
    ----------
    raw_text : original invoice text
    extraction : nested ``{field: {value, evidence}, ...}`` dict
    amount_candidates_event : the LAST ``amount_candidates`` audit-log event
        (may be None if not available)

    Each triggered rule appends its flag string to the result list.
    """
    signals: list[str] = []

    if not extraction:
        return signals

    # ---- (a) amount_not_in_total_line ----------------------------------------
    if amount_candidates_event is not None:
        candidates = amount_candidates_event.get("candidates", [])
        winning_kw = amount_candidates_event.get("winning_keyword")
        if len(candidates) > 1 and winning_kw is None:
            signals.append("amount_not_in_total_line")

    # ---- (b) amount_in_non_money_context -------------------------------------
    amount_block = extraction.get("amount")
    if isinstance(amount_block, dict):
        evidence = amount_block.get("evidence", "") or ""
        if evidence.strip():
            if (
                _PHONE_RE.search(evidence)
                or _ZIP_RE.search(evidence)
                or _INVOICE_ID_RE.search(evidence)
            ):
                signals.append("amount_in_non_money_context")

    # ---- (c) vendor_is_buyer_entity ------------------------------------------
    vendor_block = extraction.get("vendor")
    if isinstance(vendor_block, dict):
        vendor_val = (vendor_block.get("value") or "")
        vendor_ev = (vendor_block.get("evidence") or "")
        vendor_lower = vendor_val.strip().casefold()

        # Direct match against known buyer names
        if vendor_lower in _BUYER_ENTITIES:
            signals.append("vendor_is_buyer_entity")
        elif vendor_ev.strip() and raw_text.strip():
            # Check if vendor evidence only appears in a Bill-To / Ship-To block
            lines = raw_text.splitlines()
            vendor_ev_lower = vendor_ev.strip().casefold()
            in_bill_ship_block = False
            in_body = False
            found_in_block = False
            found_in_body = False

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if _BILL_SHIP_RE.match(stripped):
                    in_bill_ship_block = True
                    in_body = False
                elif in_bill_ship_block and not stripped[0].isspace() and ":" in stripped:
                    # New section header → end of bill/ship block
                    in_bill_ship_block = False
                    in_body = True
                elif not in_bill_ship_block:
                    in_body = True

                if vendor_ev_lower in stripped.casefold():
                    if in_bill_ship_block:
                        found_in_block = True
                    if in_body:
                        found_in_body = True

            if found_in_block and not found_in_body:
                signals.append("vendor_is_buyer_entity")

    # ---- (d) po_missing_digits -----------------------------------------------
    po_block = extraction.get("has_po")
    if isinstance(po_block, dict):
        po_val = po_block.get("value")
        po_ev = (po_block.get("evidence") or "")
        if po_val is True and po_ev.strip() and not re.search(r"\d", po_ev):
            signals.append("po_missing_digits")

    return signals


# ---------------------------------------------------------------------------
# Triage action plan
# ---------------------------------------------------------------------------

def generate_action_plan(
    bucket: str,
    failure_codes: list[str],
    signals: list[str],
    llm_root_cause: str | None = None,
) -> dict:
    """Return a deterministic remediation plan for a failing or suspicious invoice.

    Parameters
    ----------
    bucket : failure_bucket value (``"pass"`` for suspicious passes)
    failure_codes : verifier failure codes from the extraction attempt
    signals : invariant signal flags from ``compute_invariant_signals``
    llm_root_cause : optional root-cause string from the audit LLM layer

    Returns
    -------
    dict with keys ``owner``, ``recommended_next_steps``, ``likely_files``.
    """
    # Priority-ordered rules — first match wins.
    # Bucket rules (fatal errors) evaluated first, then signal rules (warnings).

    if bucket == "terminal_mismatch":
        plan = {
            "owner": "routing",
            "recommended_next_steps": [
                "Check routing conditions from the failing node",
                "Verify expected_status in gold record matches graph topology",
            ],
            "likely_files": ["src/normalize_graph.py", "datasets/expected.jsonl"],
        }
    elif bucket == "field_mismatch" and "AMOUNT_MISMATCH" in failure_codes:
        plan = {
            "owner": "llm_node",
            "recommended_next_steps": [
                "Review amount extraction prompt or check if amount is implicit",
                "Check evidence grounding for amount field",
            ],
            "likely_files": ["src/agent/nodes.py", "src/verifier.py"],
        }
    elif bucket == "field_mismatch" and "VENDOR_EVIDENCE_MISMATCH" in failure_codes:
        plan = {
            "owner": "llm_node",
            "recommended_next_steps": [
                "LLM returned vendor name not matching evidence",
                "Check if vendor has multiple name variants",
            ],
            "likely_files": ["src/agent/nodes.py"],
        }
    elif "po_missing_digits" in signals:
        plan = {
            "owner": "verifier",
            "recommended_next_steps": [
                r"Tighten PO_RE regex to require \d+ after PO prefix",
                "Add test case for bare PO prefix without digits",
            ],
            "likely_files": ["src/verifier.py", "tests/test_verifier.py"],
        }
    elif "amount_not_in_total_line" in signals:
        plan = {
            "owner": "llm_node",
            "recommended_next_steps": [
                "Review amount extraction prompt — LLM may be picking non-total line",
                "Add total_line hint to extraction prompt",
            ],
            "likely_files": ["src/agent/nodes.py"],
        }
    elif "amount_in_non_money_context" in signals:
        plan = {
            "owner": "dataset",
            "recommended_next_steps": [
                "Check if invoice has phone/zip that matches amount pattern",
                "Consider adding multiple_totals or noisy_header tag",
            ],
            "likely_files": ["datasets/expected.jsonl", "datasets/gold_invoices/"],
        }
    elif "vendor_is_buyer_entity" in signals:
        plan = {
            "owner": "llm_node",
            "recommended_next_steps": [
                "LLM extracted buyer entity as vendor — review extraction prompt",
                "Check if vendor evidence is in Bill To block",
            ],
            "likely_files": ["src/agent/nodes.py"],
        }
    else:
        plan = {
            "owner": "unknown",
            "recommended_next_steps": [
                "Manual investigation needed — no automated triage available",
            ],
            "likely_files": [],
        }

    if llm_root_cause:
        plan["llm_root_cause"] = llm_root_cause

    return plan
