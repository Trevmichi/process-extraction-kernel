"""
patch_logic.py
Programmatically inject missing business-logic guardrails into the extracted
AP process graph and write a patched JSON ready for the compiler.

Patches applied
---------------
1. Insert amount-threshold gateway (n_threshold) between the 3-way match
   approval branch and the APPROVE node (n5).
   - Amounts >  $10,000 → ESCALATE_TO_DIRECTOR (n_escalate)
   - Amounts <= $10,000 → APPROVE as normal (n5)

2. Seal the bad-data and No-PO loopholes after VALIDATE_FIELDS (n3).
   Priority-ordered conditional branches (n3→n4 stays unconditional fallback):
   - status == MISSING_DATA → REJECT_INVOICE (n_reject)      [bad / blank data]
   - has_po == False        → MANUAL_REVIEW_NO_PO (n_exception) [missing PO]
   - unconditional fallback → MATCH_3_WAY (n4)                 [normal path]

Usage
-----
    python patch_logic.py
"""
from __future__ import annotations

import json
from pathlib import Path

SRC_PATH = Path("outputs/ap_master_manual_auto.json")
DST_PATH = Path("outputs/ap_master_manual_auto_patched.json")


# ---------------------------------------------------------------------------
# New nodes injected by this patch
# ---------------------------------------------------------------------------
NEW_NODES: list[dict] = [
    {
        "id":       "n_threshold",
        "kind":     "gateway",
        "name":     "Amount Threshold Check — injected guardrail ($10k)",
        "action":   None,
        "decision": {"type": "THRESHOLD_AMOUNT_10K", "inputs": [], "expression": None},
        "evidence": [],
        "meta":     {"canonical_key": "gw:THRESHOLD_AMOUNT_10K"},
    },
    {
        "id":       "n_escalate",
        "kind":     "task",
        "name":     "Escalate to Director (amount exceeds $10,000 threshold)",
        "action":   {"type": "ESCALATE_TO_DIRECTOR", "actor_id": "role_director",
                     "artifact_id": "art_invoice", "extra": {}},
        "decision": None,
        "evidence": [],
        "meta":     {"canonical_key": "task:ESCALATE_TO_DIRECTOR"},
    },
    {
        "id":       "n_reject",
        "kind":     "task",
        "name":     "Reject Invoice (missing or invalid data detected)",
        "action":   {"type": "REJECT_INVOICE", "actor_id": "role_ap_clerk",
                     "artifact_id": "art_invoice", "extra": {}},
        "decision": None,
        "evidence": [],
        "meta":     {"canonical_key": "task:REJECT_INVOICE"},
    },
    {
        "id":       "n_exception",
        "kind":     "task",
        "name":     "Flag for Manual Review — No Purchase Order on file",
        "action":   {"type": "MANUAL_REVIEW_NO_PO", "actor_id": "role_ap_clerk",
                     "artifact_id": "art_invoice", "extra": {}},
        "decision": None,
        "evidence": [],
        "meta":     {"canonical_key": "task:MANUAL_REVIEW_NO_PO"},
    },
]


def _patch(data: dict) -> tuple[dict, list[str]]:
    """
    Apply all patches to *data* (a parsed ap_*.json dict) in-place.
    Returns the modified dict and a human-readable changelog.
    """
    changelog: list[str] = []

    # ------------------------------------------------------------------
    # PATCH 1 — re-route n4 approve-branch through n_threshold
    # ------------------------------------------------------------------
    # The graph has two n4→n5 edges (conditions "MATCH_3_WAY" and "match").
    # Redirect both so the compiler's dedup logic still yields one valid edge.
    n4_n5_count = 0
    for edge in data["edges"]:
        if edge.get("frm") == "n4" and edge.get("to") == "n5":
            edge["to"] = "n_threshold"
            n4_n5_count += 1
    changelog.append(
        f"  [PATCH 1] Rewired {n4_n5_count} edge(s) n4 -> n5  =>  n4 -> n_threshold"
    )

    # New threshold routing edges
    data["edges"].append(
        {"frm": "n_threshold", "to": "n_escalate", "condition": "amount>10000"}
    )
    data["edges"].append(
        {"frm": "n_threshold", "to": "n5",          "condition": "amount<=10000"}
    )
    changelog.append("  [PATCH 1] Added n_threshold -> n_escalate  (condition: amount>10000)")
    changelog.append("  [PATCH 1] Added n_threshold -> n5           (condition: amount<=10000)")

    # ------------------------------------------------------------------
    # PATCH 2 — seal the bad-data and No-PO loopholes after n3
    # ------------------------------------------------------------------
    # n3→n4 stays UNCONDITIONAL (the router's step-3b fallback takes it
    # only when all conditional branches fail → clean normal path).
    # Priority-ordered conditional branches are appended after the original
    # edge so the router evaluates them in order: bad-data first, then no-PO.
    data["edges"].append(
        {"frm": "n3", "to": "n_reject",    "condition": "status==missing_data"}
    )
    data["edges"].append(
        {"frm": "n3", "to": "n_exception", "condition": "has_po==false"}
    )
    changelog.append(
        "  [PATCH 2] n3 -> n4 edge: remains unconditional (normal-path fallback)"
    )
    changelog.append("  [PATCH 2] Added n3 -> n_reject    (condition: status==missing_data, priority 1)")
    changelog.append("  [PATCH 2] Added n3 -> n_exception (condition: has_po==false,        priority 2)")

    # ------------------------------------------------------------------
    # Inject new nodes
    # ------------------------------------------------------------------
    existing_ids = {n["id"] for n in data["nodes"]}
    added = []
    for node in NEW_NODES:
        if node["id"] not in existing_ids:
            data["nodes"].append(node)
            added.append(node["id"])
    changelog.append(f"  [NODES]   Injected: {', '.join(added)}")

    return data, changelog


def main() -> None:
    print(f"\n[patch] Loading  : {SRC_PATH}")
    data = json.loads(SRC_PATH.read_text(encoding="utf-8"))

    original_node_count = len(data["nodes"])
    original_edge_count = len(data["edges"])

    data, changelog = _patch(data)

    DST_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[patch] Written  : {DST_PATH}")
    print(f"[patch] Nodes    : {original_node_count}  ->  {len(data['nodes'])}")
    print(f"[patch] Edges    : {original_edge_count}  ->  {len(data['edges'])}")
    print("\n[patch] Changelog:")
    for line in changelog:
        print(line)
    print()


if __name__ == "__main__":
    main()
