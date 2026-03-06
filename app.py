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
from src.audit_parser import parse_audit_log
from src.explanation import build_explanation
from src.ui_audit import extract_router_events

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
        col_app.metric("Approved", counts.get("APPROVED", 0) + counts.get("PAID", 0))

        st.markdown("**Status Breakdown**")
        for s, n in sorted(counts.items()):
            icon = _STATUS_ICONS.get(s, "•")
            st.markdown(f"{icon} &nbsp; **{s}** — {n}")

        st.divider()
        st.caption("Recent invoices (latest first):")
        df = pd.DataFrame([
            {
                "ID":     r["invoice_id"],
                "Vendor": str(r["vendor"])[:16],
                "Amt":    f"${r['amount']:,.0f}" if r["amount"] else "N/A",
                "Status": r["status"],
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
})

# ---------------------------------------------------------------------------
# MAIN — Determinism & Routing Flags
# ---------------------------------------------------------------------------
st.divider()
with st.expander("Determinism & Routing Flags"):
    route_events = extract_router_events(audit_log)
    if not route_events:
        st.caption("No routing events recorded.")
    else:
        route_rows = []
        for ev in route_events:
            if "raw" in ev:
                route_rows.append({"Step": ev["raw"], "Type": "Executed"})
            else:
                target = ev.get("target", ev.get("node", ""))
                event  = ev.get("event", "")
                route_rows.append({"Step": f"{event} → {target}" if target else event, "Type": "Route"})
        st.table(pd.DataFrame(route_rows))

    st.caption(f"Final node reached: `{current_node}`" if current_node else "Final node: unknown")

# ---------------------------------------------------------------------------
# MAIN — Audit trail expander
# ---------------------------------------------------------------------------
st.divider()
with st.expander("View AI Audit Trail", expanded=True):
    if not audit_log:
        st.caption("No audit entries recorded.")
    else:
        for i, entry in enumerate(audit_log, 1):
            entry_str = str(entry)
            lower = entry_str.lower()

            if "extracted" in lower or '"event": "extraction"' in lower:
                icon, tag = "🔍", "`LLM EXTRACT`"
            elif "validation" in lower or '"event": "verifier"' in lower:
                icon = "✅" if "true" in lower else "❌"
                tag  = "`LLM VALIDATE`"
            elif any(k in lower for k in ("escalat", "reject", "exception", "flagged", "manual review")):
                icon, tag = "⚠️", "`GUARDRAIL`"
            elif "approve" in lower:
                icon, tag = "✅", "`DECISION`"
            elif "match_result" in lower:
                icon, tag = "🔗", "`MATCH`"
            elif "route" in lower or lower.startswith("executed "):
                icon, tag = "▶", "`ROUTE`"
            else:
                icon, tag = "▶", "`ROUTE`"

            st.markdown(f"{icon} &nbsp; **Step {i}** &nbsp; {tag} &nbsp; — &nbsp; {entry_str}")
