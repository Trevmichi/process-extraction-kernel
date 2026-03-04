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
   - status == "MISSING_DATA" → REJECT_INVOICE (n_reject)     [bad / blank data]
   - has_po == false          → MANUAL_REVIEW_NO_PO (n_exception) [missing PO]
   - unconditional fallback   → MATCH_3_WAY (n4)               [normal path]

3. Ensure artifact art_account_code is present in the artifacts list.
   Nodes n10 and n22 reference it but it is absent in the mined doc.

Provenance
----------
Every node and edge injected by this patch carries metadata:
  node.meta.origin   = "patch"
  node.meta.patch_id = "<patch_name>"
  node.meta.rationale = "<human-readable why>"
  edge.meta          = { "origin": "patch", "patch_id": "<patch_name>" }

Usage
-----
    python patch_logic.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src is importable when run as a top-level script
_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

SRC_PATH = Path("outputs/ap_master_manual_auto.json")
DST_PATH = Path("outputs/ap_master_manual_auto_patched.json")

# ---------------------------------------------------------------------------
# Artifact injected to fix missing reference
# ---------------------------------------------------------------------------
ART_ACCOUNT_CODE: dict = {
    "id":   "art_account_code",
    "type": "record",
    "name": "GL Account Code",
}

# ---------------------------------------------------------------------------
# New nodes injected by this patch (with origin metadata)
# ---------------------------------------------------------------------------
NEW_NODES: list[dict] = [
    {
        "id":       "n_threshold",
        "kind":     "gateway",
        "name":     "Amount Threshold Check — injected guardrail ($10k)",
        "action":   None,
        "decision": {"type": "THRESHOLD_AMOUNT_10K", "inputs": [], "expression": None},
        "evidence": [],
        "meta": {
            "canonical_key": "gw:THRESHOLD_AMOUNT_10K",
            "origin":        "patch",
            "patch_id":      "patch_1_threshold_gateway",
            "rationale":     "Guardrail: invoices >$10k must be escalated to director",
        },
    },
    {
        "id":       "n_escalate",
        "kind":     "task",
        "name":     "Escalate to Director (amount exceeds $10,000 threshold)",
        "action":   {
            "type":        "ESCALATE_TO_DIRECTOR",
            "actor_id":    "role_director",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:ESCALATE_TO_DIRECTOR",
            "origin":        "patch",
            "patch_id":      "patch_1_threshold_gateway",
            "rationale":     "Guardrail: high-value invoice escalation path",
        },
    },
    {
        "id":       "n_reject",
        "kind":     "task",
        "name":     "Reject Invoice (missing or invalid data detected)",
        "action":   {
            "type":        "REJECT_INVOICE",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:REJECT_INVOICE",
            "origin":        "patch",
            "patch_id":      "patch_2_data_loophole",
            "rationale":     "Guardrail: bad/blank field data must not proceed to matching",
        },
    },
    {
        "id":       "n_exception",
        "kind":     "task",
        "name":     "Flag for Manual Review — No Purchase Order on file",
        "action":   {
            "type":        "MANUAL_REVIEW_NO_PO",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_NO_PO",
            "origin":        "patch",
            "patch_id":      "patch_2_data_loophole",
            "rationale":     "Guardrail: missing PO must be manually reviewed, not auto-matched",
        },
    },
    {
        "id":       "n_critic_retry",
        "kind":     "task",
        "name":     "Critic Retry — LLM correction attempt for failed extraction",
        "action":   {
            "type":        "CRITIC_RETRY",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:CRITIC_RETRY",
            "origin":        "patch",
            "patch_id":      "patch_3_critic_retry",
            "rationale":     "Guardrail: one LLM correction attempt before manual review",
        },
    },
]

# ---------------------------------------------------------------------------
# Exception station nodes (fail-closed sinks for unmodeled / error paths)
# ---------------------------------------------------------------------------
_EXCEPTION_PATCH_ID = "P.EXCEPTION_STATIONS.V1"

EXCEPTION_STATIONS: list[dict] = [
    {
        "id":       "n_exc_bad_extraction",
        "kind":     "task",
        "name":     "Manual Review — Bad Extraction (evidence verification failed)",
        "action":   {
            "type":        "ROUTE_FOR_REVIEW",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {"reason": "BAD_EXTRACTION"},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_BAD_EXTRACTION",
            "intent_key":    "task:MANUAL_REVIEW_BAD_EXTRACTION",
            "origin":        "patch",
            "synthetic":     True,
            "semantic_assumption": "fail_closed_bad_extraction",
            "origin_pass":   "inject_exception_stations",
            "patch_id":      _EXCEPTION_PATCH_ID,
            "rationale":     "Fail-closed sink: extraction evidence verification failed",
        },
    },
    {
        "id":       "n_exc_unmodeled_gate",
        "kind":     "task",
        "name":     "Manual Review — Unmodeled Gateway (decision logic not captured)",
        "action":   {
            "type":        "ROUTE_FOR_REVIEW",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {"reason": "UNMODELED_GATE"},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE",
            "intent_key":    "task:MANUAL_REVIEW_UNMODELED_GATE",
            "origin":        "patch",
            "synthetic":     True,
            "semantic_assumption": "fail_closed_unmodeled",
            "origin_pass":   "inject_exception_stations",
            "patch_id":      _EXCEPTION_PATCH_ID,
            "rationale":     "Fail-closed sink: gateway has no modeled decision logic",
        },
    },
    {
        "id":       "n_exc_ambiguous_route",
        "kind":     "task",
        "name":     "Manual Review — Ambiguous Route (multiple conditions matched)",
        "action":   {
            "type":        "ROUTE_FOR_REVIEW",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {"reason": "AMBIGUOUS_ROUTE"},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE",
            "intent_key":    "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE",
            "origin":        "patch",
            "synthetic":     True,
            "semantic_assumption": "fail_closed_ambiguous",
            "origin_pass":   "inject_exception_stations",
            "patch_id":      _EXCEPTION_PATCH_ID,
            "rationale":     "Fail-closed sink: router could not disambiguate outgoing edges",
        },
    },
    {
        "id":       "n_exc_no_route",
        "kind":     "task",
        "name":     "Manual Review — No Route (no outgoing edge matched)",
        "action":   {
            "type":        "ROUTE_FOR_REVIEW",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {"reason": "NO_ROUTE"},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_NO_ROUTE",
            "intent_key":    "task:MANUAL_REVIEW_NO_ROUTE",
            "origin":        "patch",
            "synthetic":     True,
            "semantic_assumption": "fail_closed_no_route",
            "origin_pass":   "inject_exception_stations",
            "patch_id":      _EXCEPTION_PATCH_ID,
            "rationale":     "Fail-closed sink: no outgoing edge condition was satisfied",
        },
    },
]


def inject_exception_stations(data: dict) -> list[str]:
    """
    Idempotently inject fail-closed exception station nodes into *data*.

    Called before normalization passes.  Each station is a task node with
    ``action.type = "ROUTE_FOR_REVIEW"`` and a reason code in
    ``action.extra.reason``.

    Returns a human-readable changelog.
    """
    existing_ids = {n["id"] for n in data.get("nodes", [])}
    changelog: list[str] = []
    added: list[str] = []

    for station in EXCEPTION_STATIONS:
        if station["id"] not in existing_ids:
            data.setdefault("nodes", []).append(station)
            added.append(station["id"])

    if added:
        changelog.append(
            f"  [EXCEPTION STATIONS] Injected: {', '.join(added)}"
        )
    else:
        changelog.append(
            "  [EXCEPTION STATIONS] All 4 stations already present — skipped"
        )

    return changelog


# ---------------------------------------------------------------------------
# Edge metadata factory
# ---------------------------------------------------------------------------

def _edge_meta(patch_id: str) -> dict:
    """Return provenance metadata dict for a patched edge."""
    return {"origin": "patch", "patch_id": patch_id}


def _patch(data: dict) -> tuple[dict, list[str]]:
    """
    Apply all patches to *data* (a parsed ap_*.json dict) in-place.
    Returns the modified dict and a human-readable changelog.
    """
    changelog: list[str] = []

    # ------------------------------------------------------------------
    # PATCH 0 — ensure art_account_code exists in artifacts
    # ------------------------------------------------------------------
    existing_art_ids = {a["id"] for a in data.get("artifacts", [])}
    if ART_ACCOUNT_CODE["id"] not in existing_art_ids:
        data.setdefault("artifacts", []).append(ART_ACCOUNT_CODE)
        changelog.append(
            f"  [PATCH 0] Added artifact {ART_ACCOUNT_CODE['id']!r} "
            f"({ART_ACCOUNT_CODE['name']})"
        )
    else:
        changelog.append(
            f"  [PATCH 0] artifact {ART_ACCOUNT_CODE['id']!r} already present — skipped"
        )

    # ------------------------------------------------------------------
    # PATCH 1 — re-route n4 approve-branch through n_threshold
    # ------------------------------------------------------------------
    # The graph has two n4→n5 edges (conditions "MATCH_3_WAY" and "match").
    # Redirect both so the compiler's dedup logic still yields one valid edge.
    n4_n5_count = 0
    for edge in data["edges"]:
        if edge.get("frm") == "n4" and edge.get("to") == "n5":
            edge["to"] = "n_threshold"
            edge.setdefault("meta", {}).update(_edge_meta("patch_1_threshold_gateway"))
            n4_n5_count += 1
    changelog.append(
        f"  [PATCH 1] Rewired {n4_n5_count} edge(s) n4 -> n5  =>  n4 -> n_threshold"
    )

    # New threshold routing edges (canonical DSL conditions)
    data["edges"].append({
        "frm":       "n_threshold",
        "to":        "n_escalate",
        "condition": "amount > 10000",
        "meta":      _edge_meta("patch_1_threshold_gateway"),
    })
    data["edges"].append({
        "frm":       "n_threshold",
        "to":        "n5",
        "condition": "amount <= 10000",
        "meta":      _edge_meta("patch_1_threshold_gateway"),
    })
    changelog.append("  [PATCH 1] Added n_threshold -> n_escalate  (condition: amount > 10000)")
    changelog.append("  [PATCH 1] Added n_threshold -> n5           (condition: amount <= 10000)")

    # ------------------------------------------------------------------
    # PATCH 2 — seal the bad-data and No-PO loopholes after n3
    # ------------------------------------------------------------------
    # n3→n4 stays UNCONDITIONAL (the router's step-3b fallback takes it
    # only when all conditional branches fail → clean normal path).
    # Priority-ordered conditional branches use canonical DSL conditions.
    data["edges"].append({
        "frm":       "n3",
        "to":        "n_reject",
        "condition": 'status == "MISSING_DATA"',
        "meta":      _edge_meta("patch_2_data_loophole"),
    })
    _NO_PO_GUARD = (
        'status != "BAD_EXTRACTION" AND status != "NEEDS_RETRY" '
        'AND status != "MISSING_DATA" AND has_po == false'
    )
    data["edges"].append({
        "frm":       "n3",
        "to":        "n_exception",
        "condition": _NO_PO_GUARD,
        "meta":      _edge_meta("patch_2_data_loophole"),
    })
    changelog.append(
        "  [PATCH 2] n3 -> n4 edge: remains unconditional (normal-path fallback)"
    )
    changelog.append('  [PATCH 2] Added n3 -> n_reject    (condition: status == "MISSING_DATA")')
    changelog.append(f"  [PATCH 2] Added n3 -> n_exception (condition: {_NO_PO_GUARD})")

    # ------------------------------------------------------------------
    # Inject new nodes (idempotent)
    # ------------------------------------------------------------------
    existing_ids = {n["id"] for n in data["nodes"]}
    added: list[str] = []
    for node in NEW_NODES:
        if node["id"] not in existing_ids:
            data["nodes"].append(node)
            added.append(node["id"])
    changelog.append(f"  [NODES]   Injected: {', '.join(added) or '(none — already present)'}")

    return data, changelog


def main() -> None:
    from src.normalize_graph import normalize_all
    from src.linter import lint_process_graph

    print(f"\n[patch] Loading  : {SRC_PATH}")
    if not SRC_PATH.exists():
        print(f"[patch] ERROR: source file not found: {SRC_PATH}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(SRC_PATH.read_text(encoding="utf-8"))

    original_node_count = len(data["nodes"])
    original_edge_count = len(data["edges"])

    # ---- Apply patches -------------------------------------------------------
    data, changelog = _patch(data)
    print("[patch] Changelog:")
    for line in changelog:
        print(line)

    # ---- Inject exception stations (before normalization) --------------------
    exc_log = inject_exception_stations(data)
    for line in exc_log:
        print(line)

    # ---- Apply normalization passes ------------------------------------------
    print("\n[normalize] Running normalization passes ...")
    data, norm_log = normalize_all(data)
    if norm_log:
        for line in norm_log:
            print(line)
    else:
        print("  (no changes)")

    # ---- Write output --------------------------------------------------------
    DST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DST_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[patch] Written  : {DST_PATH}")
    print(f"[patch] Nodes    : {original_node_count}  ->  {len(data['nodes'])}")
    print(f"[patch] Edges    : {original_edge_count}  ->  {len(data['edges'])}")

    # ---- Sanity lint ---------------------------------------------------------
    errors   = [e for e in lint_process_graph(data) if e.severity == "error"]
    warnings = [e for e in lint_process_graph(data) if e.severity == "warning"]
    if errors:
        print(f"\n[patch] LINTER: {len(errors)} error(s) remain after normalization:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"\n[patch] LINTER: OK (0 errors, {len(warnings)} warning(s))")
    print()


if __name__ == "__main__":
    main()
