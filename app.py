"""
app.py
Enterprise AP Process Engine — Streamlit SaaS UI.

Usage
-----
    streamlit run app.py
"""
from __future__ import annotations

import time
from collections import Counter

import pandas as pd
import streamlit as st

from src.agent.compiler import build_ap_graph
from src.agent.state import APState, make_initial_state
from src.audit_parser import (
    AmountCandidatesEvent,
    ArithmeticCheckEvent,
    CriticRetryEvent,
    ExceptionStationEvent,
    ExtractionEvent,
    MatchInputsEvent,
    MatchResultSetEvent,
    PlainTextEntry,
    RouteDecisionEvent,
    RouteRecordEvent,
    RouteStepEntry,
    SequentialDispatchEvent,
    UnknownJsonEntry,
    VerifierSummaryEvent,
    parse_audit_log,
)
from src.explanation import build_explanation


# ---------------------------------------------------------------------------
# Audit trail entry formatter
# ---------------------------------------------------------------------------

def _format_audit_entry(entry) -> tuple[str, str, str]:
    """Return (icon, tag, summary) for a single typed audit entry."""
    if isinstance(entry, ExtractionEvent):
        icon = "✅" if entry.valid else "❌"
        codes = entry.reasons or entry.failure_codes or ()
        suffix = f": {', '.join(codes)}" if codes else ""
        return icon, "EXTRACT", f"Extraction {'valid' if entry.valid else 'failed'} ({entry.variant}){suffix}"

    if isinstance(entry, VerifierSummaryEvent):
        icon = "✅" if entry.valid else "❌"
        v = "✓" if entry.vendor.get("ok") else "✗"
        a = "✓" if entry.amount.get("ok") else "✗"
        p = "✓" if entry.has_po.get("ok") else "✗"
        return icon, "VERIFY", f"Verified {entry.status_before}→{entry.status_after} (vendor{v} / amount{a} / has_po{p})"

    if isinstance(entry, ExceptionStationEvent):
        return "⚠️", "EXCEPTION", f"Exception: {entry.reason} at {entry.node} (gate {entry.gateway})"

    if isinstance(entry, MatchResultSetEvent):
        return "🔗", "MATCH", f"Match: {entry.match_result} (source: {entry.source_flag or 'none'})"

    if isinstance(entry, ArithmeticCheckEvent):
        icon = "✅" if entry.passed else "❌"
        suffix = f": {', '.join(entry.codes)}" if entry.codes else ""
        return icon, "ARITHMETIC", f"Arithmetic {'passed' if entry.passed else 'failed'}{suffix}"

    if isinstance(entry, CriticRetryEvent):
        suffix = f": {', '.join(entry.failure_codes)}" if entry.failure_codes else ""
        return "🔄", "RETRY", f"Retry #{entry.attempt}: {'valid' if entry.valid else 'failed'}{suffix} → {entry.status}"

    if isinstance(entry, RouteDecisionEvent):
        return "▶", "ROUTE", f"Route {entry.from_node}→{entry.selected or '?'} ({entry.reason}, {len(entry.candidates)} candidates)"

    if isinstance(entry, RouteStepEntry):
        actor_part = f" [{entry.actor}]" if entry.actor else ""
        return "👤", "STEP", f"{entry.intent}{actor_part} at {entry.node_id}"

    if isinstance(entry, MatchInputsEvent):
        return "🔍", "INPUTS", f"Match inputs: po_match={entry.po_match}, match_3_way={entry.match_3_way}"

    if isinstance(entry, SequentialDispatchEvent):
        return "⛓️", "DISPATCH", f"Sequential from {entry.node}: {'→'.join(entry.chain)}"

    if isinstance(entry, AmountCandidatesEvent):
        summary = f"{len(entry.candidates)} candidates, selected {entry.selected if entry.selected is not None else 'none'}"
        if entry.winning_keyword:
            summary += f" ({entry.winning_keyword})"
        return "💰", "AMOUNT", summary

    if isinstance(entry, RouteRecordEvent):
        rr = entry.route_record
        gw = rr.get("gateway_id", "")
        reason = rr.get("reason", "")
        if gw or reason:
            return "📋", "RECORD", f"RouteRecord: {gw} {reason}".strip()
        return "📋", "RECORD", "RouteRecord"

    if isinstance(entry, PlainTextEntry):
        raw = entry.raw
        if len(raw) > 200:
            raw = raw[:200] + "…"
        return "📝", "TEXT", raw

    if isinstance(entry, UnknownJsonEntry):
        return "❓", "UNKNOWN", f"Unknown event: {entry.event or 'no event key'}"

    return "❓", "UNKNOWN", str(entry)


def _get_outcome_category(item: dict) -> str:
    """Extract outcome category from a history item, with fallback.

    Fallback categories mirror active-view outcome semantics:
    success / rejection / exception / in_progress / unknown.
    """
    expl = item.get("explanation")
    if expl and isinstance(expl, dict):
        outcome = expl.get("outcome")
        if outcome and isinstance(outcome, dict):
            cat = outcome.get("category")
            if cat:
                return cat
    # Fallback for old items: derive from status
    status = item.get("status", "")
    if status in ("APPROVED", "PAID", "CLOSED"):
        return "success"
    if status.startswith("EXCEPTION_"):
        return "exception"
    if status in ("REJECTED", "ESCALATED", "BAD_EXTRACTION", "MISSING_DATA"):
        return "rejection"
    if status in ("NEW", "DATA_EXTRACTED", "NEEDS_RETRY", "VALIDATED", "PENDING_INFO"):
        return "in_progress"
    return "unknown"


def _get_history_summary(item: dict) -> str:
    """Derive a compact summary string from a history item's explanation dict.

    Priority chain (first match wins):
    exception > extraction failure > arithmetic failure > match > clean pass > fallback.
    Only emits "Clean pass" when an explanation dict is present.
    """
    expl = item.get("explanation")
    if not expl or not isinstance(expl, dict):
        status = item.get("status")
        return f"Status: {status}" if status else "No structured summary"

    # 1. Exception
    exc = expl.get("exception")
    if exc and isinstance(exc, dict):
        reason = exc.get("reason")
        if reason:
            return f"Exception: {reason}"

    # 2. Extraction failure
    ext = expl.get("extraction")
    if ext and isinstance(ext, dict):
        if ext.get("valid") is False:
            codes = ext.get("failure_codes")
            if codes and isinstance(codes, (list, tuple)):
                return f"Extraction failed: {', '.join(str(c) for c in codes)}"
            return "Extraction failed"

    # 3. Arithmetic failure
    arith = expl.get("arithmetic")
    if arith and isinstance(arith, dict):
        if arith.get("passed") is False:
            codes = arith.get("failure_codes")
            code_str = ", ".join(str(c) for c in codes) if codes and isinstance(codes, (list, tuple)) else ""
            delta = arith.get("total_sum_delta")
            if delta is None:
                delta = arith.get("tax_rate_delta")
            suffix = f" (Δ {delta})" if delta is not None else ""
            return f"Arithmetic failed: {code_str}{suffix}".rstrip(": ")

    # 4. Match
    match = expl.get("match")
    if match and isinstance(match, dict):
        result = match.get("match_result", "UNKNOWN")
        source = match.get("source_flag")
        via = f" via {source}" if source else ""
        return f"Match: {result}{via}"

    # 5. Clean pass (only when explanation exists)
    if _get_outcome_category(item) == "success":
        return "Clean pass"

    # 6. Fallback
    status = item.get("status")
    return f"Status: {status}" if status else "No structured summary"


def _build_operator_review(explanation) -> dict | None:
    """Build a compact operator review summary for non-success outcomes.

    Returns None for success outcomes or missing explanation.
    Otherwise returns {"primary_issue", "supporting_signals", "review_focus"}.
    """
    if explanation is None:
        return None
    if not hasattr(explanation, "outcome") or explanation.outcome is None:
        return None
    if explanation.outcome.category == "success":
        return None

    primary_issue = ""
    signals: list[str] = []
    review_focus = "Review the structured audit sections below for the strongest failure signal."

    # Priority 1: Exception
    if explanation.exception is not None:
        reason = explanation.exception.reason or "UNKNOWN"
        primary_issue = f"Exception: {reason}"
        signals.append(f"Reason: {reason}")
        if explanation.extraction is not None and not explanation.extraction.valid:
            codes = explanation.extraction.failure_codes
            if codes:
                signals.append(f"Extraction codes: {', '.join(codes)}")
        if explanation.arithmetic is not None and not explanation.arithmetic.passed:
            codes = explanation.arithmetic.failure_codes
            if codes:
                signals.append(f"Arithmetic codes: {', '.join(codes)}")
        if reason == "NO_PO":
            review_focus = "Confirm whether this invoice should follow a non-PO workflow or requires a valid PO."
        elif reason == "BAD_EXTRACTION":
            review_focus = "Review source text quality and extracted fields before manual handling."
        else:
            review_focus = "Review the exception reason and routing context in the audit trail below."

    # Priority 2: Extraction failure
    elif explanation.extraction is not None and not explanation.extraction.valid:
        primary_issue = "Extraction verification failed"
        codes = explanation.extraction.failure_codes
        if codes:
            signals.append(f"Failure codes: {', '.join(codes)}")
        if explanation.retry is not None:
            signals.append(f"Retries: {explanation.retry.total_attempts}")
            if explanation.retry.final_status:
                signals.append(f"Retry final status: {explanation.retry.final_status}")
        review_focus = "Inspect invoice text and evidence anchors for vendor, amount, and PO extraction."

    # Priority 3: Arithmetic failure
    elif explanation.arithmetic is not None and not explanation.arithmetic.passed:
        primary_issue = "Invoice arithmetic inconsistency"
        codes = explanation.arithmetic.failure_codes
        if codes:
            signals.append(f"Arithmetic codes: {', '.join(codes)}")
        delta = explanation.arithmetic.total_sum_delta
        if delta is None:
            delta = explanation.arithmetic.tax_rate_delta
        if delta is not None:
            signals.append(f"Delta: {delta}")
        review_focus = "Check subtotal, tax, fees, and stated total for internal consistency."

    # Priority 4: Match problem
    elif explanation.match is not None and explanation.match.match_result != "MATCH":
        primary_issue = f"Match result: {explanation.match.match_result}"
        signals.append(f"Match result: {explanation.match.match_result}")
        if explanation.match.source_flag:
            signals.append(f"Match source: {explanation.match.source_flag}")
        review_focus = "Review PO / 3-way match inputs and determine why the invoice did not cleanly match."

    # Priority 5: Fallback
    else:
        primary_issue = f"Outcome: {explanation.outcome.category}"
        if explanation.outcome.final_status:
            signals.append(f"Status: {explanation.outcome.final_status}")

    return {
        "primary_issue": primary_issue,
        "supporting_signals": signals[:4],
        "review_focus": review_focus,
    }



# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="AP AI Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — metric cards + hide default Streamlit chrome
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* Metric cards */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1a1f3c 0%, #252b45 100%);
    border-radius: 10px;
    padding: 20px 24px;
    border: 1px solid rgba(99, 179, 237, 0.15);
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
}
[data-testid="stMetricLabel"] {
    font-size: 0.73rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    opacity: 0.6;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem;
    font-weight: 700;
}
/* Hide default Streamlit chrome */
#MainMenu          { visibility: hidden; }
.stAppDeployButton { display: none;      }
footer             { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
if "history" not in st.session_state:
    st.session_state.history: list[dict] = []
if "po_match_val" not in st.session_state:
    st.session_state.po_match_val: bool = True

# ---------------------------------------------------------------------------
# Mock invoice presets
# ---------------------------------------------------------------------------
MOCK_INVOICES: dict[str, dict] = {
    "Standard — $250 (Office Supplies)": {
        "text":     "INVOICE #001\nVendor: Office Supplies Co\nTotal: $250.00\nPO: PO-1122",
        "po_match": True,
    },
    "High-Value — $45,000 (Enterprise Servers)": {
        "text":     "INVOICE #002\nVendor: Enterprise Servers Inc\nTotal: $45,000.00\nPO: PO-9988",
        "po_match": True,
    },
    "No-PO — $850 (Local Catering)": {
        "text":     "INVOICE #003\nVendor: Local Catering\nTotal: $850.00\nPO: None",
        "po_match": False,
    },
    "Bad Data — Blank Amount": {
        "text":     "INVOICE #004\nVendor: Unknown\nTotal: BLANK\nPO: N/A",
        "po_match": False,
    },
}

# ---------------------------------------------------------------------------
# Cached graph
# ---------------------------------------------------------------------------
@st.cache_resource
def load_agent():
    """Compile and cache the LangGraph from the patched SOP JSON."""
    try:
        return build_ap_graph("outputs/ap_master_manual_auto_patched.json")
    except ValueError as exc:
        return exc


_agent_or_error = load_agent()

if isinstance(_agent_or_error, ValueError):
    st.error("Graph invalid — cannot compile")
    st.code(str(_agent_or_error), language="text")
    st.stop()

agent = _agent_or_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_invoice_id(raw_text: str) -> str:
    first_line = raw_text.strip().splitlines()[0] if raw_text.strip() else ""
    if "#" in first_line:
        return "INV-" + first_line.split("#")[-1].strip()
    return f"INV-{int(time.time()) % 10000:04d}"


def _sync_po_match_from_example() -> None:
    """on_change callback: keeps the PO Match checkbox in sync with the example."""
    label = st.session_state.get("example_select", "")
    st.session_state.po_match_val = MOCK_INVOICES.get(label, {}).get("po_match", True)


def _reset_po_match_on_paste() -> None:
    """on_change callback: reset PO Match to False when user modifies pasted text."""
    st.session_state.po_match_val = False


_STATUS_ICONS = {
    "APPROVED":                "✅",
    "PAID":                    "✅",
    "ESCALATED":               "⚠️",
    "EXCEPTION_NO_PO":         "⚠️",
    "EXCEPTION_MATCH_FAILED":  "⚠️",
    "EXCEPTION_UNMODELED":     "⚠️",
    "EXCEPTION_AMBIGUOUS_ROUTE":"⚠️",
    "EXCEPTION_NO_ROUTE":      "⚠️",
    "BAD_EXTRACTION":          "❌",
    "REJECTED":                "❌",
    "MISSING_DATA":            "❌",
}


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Control Panel")
    st.caption("AP Automation Engine v2.0")
    st.divider()

    po_match: bool = st.checkbox(
        "PO Record Matched",
        key="po_match_val",
        help=(
            "Whether the invoice line-items reconcile against the PO on file. "
            "Auto-synced when a Test Example is selected."
        ),
    )

    st.divider()
    st.subheader("📋 Batch Ledger")

    history: list[dict] = st.session_state.history

    if not history:
        st.caption("No invoices processed yet.")
    else:
        counts = Counter(r["status"] for r in history)

        col_tot, col_app = st.columns(2)
        col_tot.metric("Total",    len(history))
        success_count = sum(1 for r in history if _get_outcome_category(r) == "success")
        col_app.metric("Successful", success_count)

        st.markdown("**Status Breakdown**")
        for s, n in sorted(counts.items()):
            icon = _STATUS_ICONS.get(s, "•")
            st.markdown(f"{icon} &nbsp; **{s}** — {n}")

        st.divider()
        st.caption("Recent invoices (latest first):")
        df = pd.DataFrame([
            {
                "ID":      r["invoice_id"],
                "Vendor":  str(r["vendor"])[:16],
                "Amt":     f"${r['amount']:,.0f}" if r["amount"] else "N/A",
                "Status":  r["status"],
                "Outcome": _get_outcome_category(r),
                "Summary": _get_history_summary(r),
            }
            for r in reversed(history[-8:])
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        if st.button("Clear History", use_container_width=True):
            st.session_state.history = []
            st.rerun()

# ---------------------------------------------------------------------------
# MAIN — Header
# ---------------------------------------------------------------------------
st.title("Enterprise AP Process Engine")
st.caption(
    "Powered by **LangGraph** + **Ollama gemma3:12b** &nbsp;·&nbsp; "
    "Patched SOP: \\$10k director-escalation &nbsp;·&nbsp; "
    "No-PO exception &nbsp;·&nbsp; Bad-data rejection"
)
st.divider()

# ---------------------------------------------------------------------------
# MAIN — Tabbed input
# ---------------------------------------------------------------------------
tab_paste, tab_upload, tab_examples = st.tabs(["Paste Text", "Upload File", "Test Examples"])

raw_text_paste  = ""
raw_text_upload = ""

with tab_paste:
    raw_text_paste = st.text_area(
        "Invoice text",
        height=220,
        placeholder=(
            "INVOICE #XXXX\n"
            "Vendor: Acme Corp\n"
            "Total: $12,500.00\n"
            "PO: PO-7742"
        ),
        label_visibility="collapsed",
        on_change=_reset_po_match_on_paste,
    )

with tab_upload:
    uploaded = st.file_uploader(
        "Upload plain-text invoice",
        type=["txt"],
        label_visibility="collapsed",
    )
    if uploaded:
        raw_text_upload = uploaded.read().decode("utf-8", errors="replace")
        st.text_area(
            "File contents",
            value=raw_text_upload,
            height=180,
            disabled=True,
            label_visibility="collapsed",
        )

with tab_examples:
    example_label: str = st.selectbox(
        "Test invoice",
        options=list(MOCK_INVOICES.keys()),
        key="example_select",
        on_change=_sync_po_match_from_example,
        label_visibility="collapsed",
    )
    mock = MOCK_INVOICES[example_label]
    st.text_area(
        "Preview",
        value=mock["text"],
        height=180,
        disabled=True,
        label_visibility="collapsed",
    )
    match_label = "Yes" if mock["po_match"] else "No"
    st.caption(
        f"PO Match for this example: **{match_label}** "
        f"(auto-synced to the Control Panel checkbox)"
    )

# Resolve raw_text: paste wins > upload > current example
if raw_text_paste.strip():
    raw_text = raw_text_paste
elif raw_text_upload.strip():
    raw_text = raw_text_upload
else:
    raw_text = mock["text"]

# ---------------------------------------------------------------------------
# MAIN — Process button
# ---------------------------------------------------------------------------
st.divider()
process_btn = st.button(
    "Process Document",
    type="primary",
    use_container_width=True,
    disabled=not raw_text.strip(),
)

if not process_btn:
    st.stop()

# ---------------------------------------------------------------------------
# MAIN — Execution with live status widget
# ---------------------------------------------------------------------------
with st.status("Agent processing invoice...", expanded=True) as status:
    st.write("Initializing LLM pipeline...")
    time.sleep(0.3)

    inv_id = _parse_invoice_id(raw_text)
    st.write(f"Extracting structured variables from invoice text — {inv_id} ...")

    initial_state: APState = make_initial_state(
        invoice_id=inv_id,
        raw_text=raw_text,
        po_match=po_match,
    )

    result: APState = agent.invoke(initial_state)

    st.write("Routing via deterministic graph... finalizing decision.")
    time.sleep(0.2)

    status.update(label="Processing Complete!", state="complete", expanded=False)

# ---------------------------------------------------------------------------
# MAIN — LLM backend error check
# ---------------------------------------------------------------------------
_extraction = result.get("extraction", {})
if isinstance(_extraction, dict) and "_error" in _extraction:
    st.error(
        "**LLM Backend Error** — extraction could not complete.  \n"
        f"Error: `{_extraction['_error']}`  \n"
        "Check that Ollama is running: `ollama serve`"
    )

# ---------------------------------------------------------------------------
# MAIN — Results: metrics + status banner
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Extraction & Routing Decision")

vendor_val    = result.get("vendor") or "N/A"
amount_val    = result.get("amount", 0.0)
has_po_val    = result.get("has_po", False)
status_val    = result.get("status", "UNKNOWN")
match_res_val = result.get("match_result", "UNKNOWN")
current_node  = result.get("current_node", "")
amount_str    = f"${amount_val:,.2f}" if amount_val else "N/A"

audit_log: list = result.get("audit_log", [])

parsed = parse_audit_log(audit_log)
explanation = build_explanation(parsed, final_status=status_val)

# --- Exception banner (top-priority signal) ---
if explanation.exception is not None:
    st.error(
        f"**Exception Station Reached** — reason: **{explanation.exception.reason}**"
        + (f"  (node: `{explanation.exception.node}`)" if explanation.exception.node else "")
    )

# --- Metric cards ---
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Vendor",       vendor_val)
c2.metric("Amount",       amount_str)
c3.metric("Has PO",       "Yes" if has_po_val else "No")
c4.metric("Match Result", match_res_val)
c5.metric("Final Status", status_val)

# Colour-coded status banner (driven by ExplanationReport outcome)
_cat = explanation.outcome.category
if _cat == "success":
    st.success(f"**{inv_id}** — Invoice **{status_val}** ✅")
elif _cat == "exception":
    if status_val == "EXCEPTION_NO_PO":
        st.warning(
            f"**{inv_id}** — Flagged for manual review ⚠️  "
            "(No Purchase Order found on file)"
        )
    else:
        st.warning(f"**{inv_id}** — Exception: **{status_val}** ⚠️")
elif _cat == "rejection":
    if status_val == "ESCALATED":
        st.warning(
            f"**{inv_id}** — Escalated for director review ⚠️  "
            "(Amount exceeds the \\$10,000 approval threshold)"
        )
    elif status_val == "BAD_EXTRACTION":
        st.error(
            f"**{inv_id}** — **Bad Extraction** ❌  "
            "(Evidence verification failed — invoice rejected)"
        )
    else:
        st.error(
            f"**{inv_id}** — **{status_val}** ❌  "
            "(Missing or invalid invoice data — please resubmit)"
        )
else:
    st.info(f"**{inv_id}** — Status: **{status_val}**")

# --- Operator review ---
review = _build_operator_review(explanation)
if review is not None:
    _signals = "\n".join(f"- {s}" for s in review["supporting_signals"])
    _body = f"**Primary issue:** {review['primary_issue']}\n\n"
    if _signals:
        _body += f"**Supporting signals:**\n{_signals}\n\n"
    _body += f"**Review focus:** {review['review_focus']}"
    st.warning(f"**Operator Review**\n\n{_body}")

# --- Verifier summary ---
if explanation.extraction is not None:
    if explanation.extraction.valid:
        st.success("Extraction verified — all evidence grounded ✅")
    else:
        _codes = explanation.extraction.failure_codes
        st.warning(
            f"Extraction verification failed ⚠️ — "
            f"reasons: {', '.join(_codes) if _codes else 'unknown'}"
        )

# --- Arithmetic consistency ---
if explanation.arithmetic is not None:
    if explanation.arithmetic.passed:
        st.caption("Arithmetic checks passed ✅")
    else:
        _arith_msg = (
            "Invoice arithmetic inconsistency detected ⚠️ — "
            f"codes: {', '.join(explanation.arithmetic.failure_codes) or 'unknown'}"
        )
        if explanation.arithmetic.total_sum_delta:
            _arith_msg += f"  |  total Δ {explanation.arithmetic.total_sum_delta}"
        if explanation.arithmetic.tax_rate_delta:
            _arith_msg += f"  |  tax rate Δ {explanation.arithmetic.tax_rate_delta}"
        st.warning(_arith_msg)

# --- Match result detail ---
if explanation.match is not None:
    _mr = explanation.match.match_result
    _sf = explanation.match.source_flag
    st.caption(f"Match result: **{_mr}** (source: `{_sf}`)" if _sf else f"Match result: **{_mr}**")

# Persist to session history
st.session_state.history.append({
    "invoice_id": inv_id,
    "vendor":     vendor_val,
    "amount":     amount_val,
    "status":     status_val,
    "explanation": explanation.to_dict() if explanation is not None and hasattr(explanation, "to_dict") else None,
})

# ---------------------------------------------------------------------------
# MAIN — Determinism & Routing Flags
# ---------------------------------------------------------------------------
st.divider()
with st.expander("Determinism & Routing Flags"):
    route_rows: list[dict] = []
    if explanation.routing is not None:
        for d in explanation.routing.decisions:
            route_rows.append({
                "Type": "Gateway",
                "Node": d.gateway_id,
                "Target": d.selected or "—",
                "Reason": d.reason,
                "Candidates": d.candidate_count,
            })
    for e in parsed.entries:
        if isinstance(e, RouteStepEntry):
            route_rows.append({
                "Type": "Step",
                "Node": e.node_id,
                "Target": "—",
                "Reason": e.intent,
                "Candidates": "—",
            })
    if route_rows:
        st.table(pd.DataFrame(route_rows))
    else:
        st.caption("No routing decisions recorded.")

    st.caption(f"Final node reached: `{current_node}`" if current_node else "Final node: unknown")

# ---------------------------------------------------------------------------
# MAIN — Audit trail expander
# ---------------------------------------------------------------------------
st.divider()
with st.expander("View AI Audit Trail", expanded=True):
    if not parsed.entries:
        st.caption("No audit entries recorded.")
    else:
        for i, entry in enumerate(parsed.entries, 1):
            icon, tag, summary = _format_audit_entry(entry)
            st.markdown(f"{icon} &nbsp; **Step {i}** &nbsp; `{tag}` &nbsp; — &nbsp; {summary}")
