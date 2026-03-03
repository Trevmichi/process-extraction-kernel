"""
run_agent.py
Execute the compiled LangGraph AP process agent against a mock invoice.

Usage
-----
    python run_agent.py [path/to/ap_*_auto.json]

Default JSON path: outputs/ap_master_manual_auto.json
"""
from __future__ import annotations

import sys
from pprint import pprint

from src.agent.compiler import build_ap_graph
from src.agent.state import APState


# ---------------------------------------------------------------------------
# Mock invoice — raw text; ENTER_RECORD and VALIDATE_FIELDS nodes will
# call the local LLM to extract and validate the structured fields.
# ---------------------------------------------------------------------------
MOCK_INVOICE: APState = {
    "invoice_id":       "INV-1001",
    "vendor":           "",       # to be extracted by LLM at ENTER_RECORD
    "amount":           0.0,      # to be extracted by LLM at ENTER_RECORD
    "has_po":           False,    # to be extracted by LLM at ENTER_RECORD
    "po_match":         True,     # within tolerance → APPROVE path after 3-way match
    "match_3_way":      True,     # mirrors po_match
    "match_result":     "UNKNOWN",  # set by MATCH_3_WAY node
    "status":           "NEW",
    "current_node":     "",
    "audit_log":        [],
    "raw_text": (
        "INVOICE #9921\n"
        "From: Acme Corp\n"
        "Total Due: $15,000.00\n"
        "Includes PO Number: PO-55421"
    ),
    "extraction":       {},
    "provenance":       {},
}


def main() -> None:
    json_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/ap_master_manual_auto.json"

    print(f"\n{'=' * 60}")
    print("  AP Process Agent — LangGraph Runner")
    print(f"  Graph source : {json_path}")
    print(f"{'=' * 60}")
    print("\n[run_agent] Building graph …")

    graph = build_ap_graph(json_path)

    print("[run_agent] Graph compiled. Invoking with mock invoice:\n")
    pprint(dict(MOCK_INVOICE), sort_dicts=False)

    print(f"\n{'-' * 60}")
    print("[run_agent] Executing …")
    print(f"{'-' * 60}\n")

    final_state: APState = graph.invoke(MOCK_INVOICE)

    print(f"\n{'=' * 60}")
    print("  FINAL STATE")
    print(f"{'=' * 60}")
    print(f"  invoice_id   : {final_state['invoice_id']}")
    print(f"  vendor       : {final_state['vendor']}")
    print(f"  amount       : {final_state['amount']}")
    print(f"  has_po       : {final_state['has_po']}")
    print(f"  po_match     : {final_state['po_match']}")
    print(f"  status       : {final_state['status']}")
    print(f"  current_node : {final_state['current_node']}")
    print(f"  raw_text     : {final_state.get('raw_text', '')[:50]}...")

    print(f"\n{'=' * 60}")
    print("  AUDIT LOG  (execution path)")
    print(f"{'=' * 60}")
    for i, entry in enumerate(final_state["audit_log"], 1):
        print(f"  {i:>3}. {entry}")

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
