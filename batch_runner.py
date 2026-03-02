"""
batch_runner.py
Batch-process multiple raw text invoices through the compiled LangGraph AP agent.

Simulates reading from an invoice queue, running each through the agent,
and producing a formatted summary report.

Usage
-----
    python batch_runner.py [path/to/ap_*_auto.json]

Default JSON path: outputs/ap_master_manual_auto.json
"""
from __future__ import annotations

import sys
from collections import defaultdict

from src.agent.compiler import build_ap_graph
from src.agent.state import APState


# ---------------------------------------------------------------------------
# Mock invoice queue — raw text as it would arrive from email/scan/ERP
# ---------------------------------------------------------------------------
RAW_INVOICES: list[str] = [
    # inv1 — Standard, small amount, valid PO
    (
        "INVOICE #001\n"
        "Vendor: Office Supplies Co\n"
        "Total: $250.00\n"
        "PO: PO-1122"
    ),
    # inv2 — Over threshold, valid PO
    (
        "INVOICE #002\n"
        "Vendor: Enterprise Servers Inc\n"
        "Total: $45,000.00\n"
        "PO: PO-9988"
    ),
    # inv3 — Missing PO
    (
        "INVOICE #003\n"
        "Vendor: Local Catering\n"
        "Total: $850.00\n"
        "PO: None"
    ),
    # inv4 — Bad / incomplete data
    (
        "INVOICE #004\n"
        "Vendor: Unknown\n"
        "Total: BLANK\n"
        "PO: N/A"
    ),
]

# Per-invoice po_match flag — reflects whether the invoice amount/line-items
# reconcile against the PO on file (a real system would query the PO DB here).
_PO_MATCH_FLAGS: list[bool] = [True, True, False, False]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_invoice_id(raw_text: str, fallback: str) -> str:
    """Extract invoice number from first line: 'INVOICE #001' → 'INV-001'."""
    first_line = raw_text.splitlines()[0]
    if "#" in first_line:
        return "INV-" + first_line.split("#")[-1].strip()
    return fallback


def _status_bucket(status: str) -> str:
    """Map a final APState status to a human summary category."""
    if status in ("APPROVED", "PAID"):
        return "Approved"
    if status in ("MISSING_DATA", "REJECTED"):
        return "Failed"
    return "Pending Review"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    json_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/ap_master_manual_auto_patched.json"

    print(f"\n{'=' * 70}")
    print("  AP Batch Runner - LangGraph Agent")
    print(f"  Graph source : {json_path}")
    print(f"{'=' * 70}")
    print("[batch] Compiling graph ...")

    graph = build_ap_graph(json_path)

    print(f"[batch] Graph ready. Processing {len(RAW_INVOICES)} invoices ...\n")

    rows: list[dict] = []
    summary: dict[str, int] = defaultdict(int)

    for idx, raw_text in enumerate(RAW_INVOICES):
        inv_id = _parse_invoice_id(raw_text, fallback=f"INV-{idx + 1:03d}")
        print(f"  [{idx + 1}/{len(RAW_INVOICES)}] {inv_id} ... ", end="", flush=True)

        initial_state: APState = {
            "invoice_id":       inv_id,
            "vendor":           "",       # extracted by ENTER_RECORD smart node
            "amount":           0.0,      # extracted by ENTER_RECORD smart node
            "has_po":           False,    # extracted by ENTER_RECORD smart node
            "po_match":         _PO_MATCH_FLAGS[idx],
            "status":           "NEW",
            "current_node":     "",
            "audit_log":        [],
            "raw_invoice_text": raw_text,
        }

        result: APState = graph.invoke(initial_state)

        final_status = result.get("status", "UNKNOWN")
        rows.append({
            "invoice_id": inv_id,
            "vendor":     result.get("vendor") or "(not extracted)",
            "amount":     result.get("amount", 0.0),
            "status":     final_status,
        })
        summary[_status_bucket(final_status)] += 1
        print(f"done  ->  {final_status}")

    # ---- Formatted results table ----------------------------------------
    print(f"\n{'=' * 70}")
    print("  BATCH RESULTS")
    print(f"{'=' * 70}")
    print(f"  {'Invoice':<12} {'Vendor':<26} {'Amount':>12}  {'Status'}")
    print(f"  {'-' * 65}")

    for row in rows:
        amount_str = f"${row['amount']:,.2f}" if row["amount"] else "N/A"
        print(
            f"  {row['invoice_id']:<12} "
            f"{str(row['vendor'])[:25]:<26} "
            f"{amount_str:>12}  "
            f"{row['status']}"
        )

    # ---- Aggregate summary ----------------------------------------------
    total    = len(rows)
    approved = summary.get("Approved",       0)
    pending  = summary.get("Pending Review", 0)
    failed   = summary.get("Failed",         0)

    print(f"\n{'=' * 70}")
    print("  SUMMARY")
    print(f"  {'Total Processed':<20}: {total}")
    print(f"  {'Approved':<20}: {approved}")
    print(f"  {'Pending Review':<20}: {pending}")
    print(f"  {'Failed':<20}: {failed}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
