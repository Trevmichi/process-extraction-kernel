"""
normalize_graph.py
Post-processing repair passes for AP process graph JSON.

``normalize_all(data)`` runs every pass in order and returns the repaired
graph dict plus a human-readable changelog.  All passes are idempotent —
running them a second time on the already-repaired graph is a no-op.

Pass order
----------
1.  fix_artifact_references        — inject art_account_code; fix empty artifact_ids
2.  fix_canonical_key_duplicates   — suffix duplicate canonical_keys with @node_id
3.  normalize_edge_conditions      — replace raw labels with canonical DSL strings
4.  inject_exception_nodes         — add n_no_match and n_manual_review_gate
5.  fix_match3way_gateway          — repair MATCH_3_WAY (n4) fan-out
5b. fix_secondary_match_gateways   — repair other MATCH_3_WAY gateways (e.g. n5)
6.  fix_main_execution_path        — wire n7 -> end node instead of n8
7.  fix_haspo_gateway              — repair HAS_PO (n8) fan-out + linear chain
8.  fix_placeholder_gateways       — resolve IF_CONDITION and SCHEDULE_PAYMENT edges
9.  convert_unparseable_gateways   — catch-all: any gateway with unparseable conditions
10. convert_whitelisted_fanout     — HAS_PO / APPROVE_OR_REJECT fan-out → sequential chain
11. convert_fanout_gateways        — catch-all: fan-out gateways -> ambiguous station
12. wire_bad_extraction_route      — ENTER_RECORD -> reject on BAD_EXTRACTION
13. inject_match_result_unknown    — UNKNOWN guardrail edges on match_result gateways
14. deduplicate_edges              — remove identical (frm,to,condition) pairs
15. deduplicate_edges_strict       — safety-net final dedup

Design constraints
------------------
* No inferred business logic: if a path cannot be made explicit from
  existing APState fields, it routes to a named exception node.
* All injected nodes / edges are marked origin="normalize".
* Functions are applied to the graph in-place for efficiency; each
  returns (data, changelog_lines).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

from .conditions import normalize_condition


# ---------------------------------------------------------------------------
# Provenance helper
# ---------------------------------------------------------------------------

def _norm_meta(patch_id: str, rationale: str) -> dict:
    """

    Args:
      patch_id: str:
      rationale: str:
      patch_id: str: 
      rationale: str: 

    Returns:

    """
    return {"origin": "normalize", "patch_id": patch_id, "rationale": rationale}


def _norm_edge(frm: str, to: str, condition, patch_id: str) -> dict:
    """

    Args:
      frm: str:
      to: str:
      condition: 
      patch_id: str:
      frm: str: 
      to: str: 
      patch_id: str: 

    Returns:

    """
    return {
        "frm":       frm,
        "to":        to,
        "condition": condition,
        "meta":      _norm_meta(patch_id, f"normalize: {frm}->{to}"),
    }


# ---------------------------------------------------------------------------
# Exception nodes injected when a branch cannot be made explicit
# ---------------------------------------------------------------------------

_EXCEPTION_NODES: dict[str, dict] = {
    "n_no_match": {
        "id":       "n_no_match",
        "kind":     "task",
        "name":     "Manual Review — 3-Way Match Failed",
        "action":   {
            "type":        "MANUAL_REVIEW_MATCH_FAILED",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_MATCH_FAILED@n_no_match",
            "intent_key":    "task:MANUAL_REVIEW_MATCH_FAILED",
            **_norm_meta(
                "normalize_gateway_fanout",
                "Fail-closed: 3-way match failure routes to manual review",
            ),
        },
    },
    "n_manual_review_gate": {
        "id":       "n_manual_review_gate",
        "kind":     "task",
        "name":     "Manual Review — Unmodeled Gateway",
        "action":   {
            "type":        "MANUAL_REVIEW_UNMODELED_GATE",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        },
        "decision": None,
        "evidence": [],
        "meta": {
            "canonical_key": "task:MANUAL_REVIEW_UNMODELED_GATE@n_manual_review_gate",
            "intent_key":    "task:MANUAL_REVIEW_UNMODELED_GATE",
            **_norm_meta(
                "normalize_placeholder_gateways",
                "Fail-closed: gateway logic is unmodeled, route to manual review",
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node_by_id(data: dict) -> dict[str, dict]:
    """

    Args:
      data: dict:
      data: dict: 

    Returns:

    """
    return {n["id"]: n for n in data.get("nodes", [])}


def _edges_from(data: dict, frm: str) -> list[dict]:
    """

    Args:
      data: dict:
      frm: str:
      data: dict: 
      frm: str: 

    Returns:

    """
    return [e for e in data.get("edges", []) if e.get("frm") == frm]


def _remove_edges(data: dict, predicate: Callable[[dict], bool]) -> int:
    """Remove edges matching *predicate*; return count removed.

    Args:
      data: dict:
      predicate: Callable[[dict]:
      bool]: 
      data: dict: 
      predicate: Callable[[dict]: 

    Returns:

    """
    before = len(data["edges"])
    data["edges"] = [e for e in data["edges"] if not predicate(e)]
    return before - len(data["edges"])


def _has_edge(data: dict, frm: str, to: str) -> bool:
    """

    Args:
      data: dict:
      frm: str:
      to: str:
      data: dict: 
      frm: str: 
      to: str: 

    Returns:

    """
    return any(e.get("frm") == frm and e.get("to") == to for e in data.get("edges", []))


def _end_node_id(data: dict) -> str | None:
    """

    Args:
      data: dict:
      data: dict: 

    Returns:

    """
    for n in data.get("nodes", []):
        if n.get("kind") == "end":
            return n["id"]
        if (n.get("meta") or {}).get("canonical_key") == "end:end":
            return n["id"]
    return None


def _is_match3way_gateway(node: dict) -> bool:
    """

    Args:
      node: dict:
      node: dict: 

    Returns:

    """
    if node.get("kind") != "gateway":
        return False
    meta = node.get("meta") or {}
    decision = node.get("decision") or {}
    ik = meta.get("intent_key") or ""
    ck = meta.get("canonical_key") or ""
    dt = decision.get("type") or ""
    return (
        "gw:MATCH_3_WAY" in ik
        or "gw:MATCH_3_WAY" in ck
        or dt == "MATCH_3_WAY"
    )


# ===========================================================================
# Pass 1 — Artifact references
# ===========================================================================

_ART_ACCOUNT_CODE = {
    "id":   "art_account_code",
    "type": "record",
    "name": "GL Account Code",
}


def fix_artifact_references(data: dict) -> tuple[dict, list[str]]:
    """1. Inject ``art_account_code`` artifact if missing.
    2. Replace empty ``action.artifact_id`` with ``art_invoice`` on
       RECEIVE_MESSAGE (and similar intake) nodes.
    
    Contract
    --------
    Pre:     ``data`` has ``artifacts`` and ``nodes`` lists.
    Post:    ``art_account_code`` in artifacts; RECEIVE_MESSAGE nodes have non-empty ``artifact_id``.
    Mutates: ``data['artifacts']``, node ``action.artifact_id`` + ``meta``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []

    # Inject art_account_code idempotently
    existing_art = {a["id"] for a in data.get("artifacts", [])}
    if "art_account_code" not in existing_art:
        data.setdefault("artifacts", []).append(_ART_ACCOUNT_CODE)
        log.append("  [ART] Injected artifact art_account_code (GL Account Code)")
    else:
        log.append("  [ART] art_account_code already present")

    # Fix empty artifact_ids
    art_ids = {a["id"] for a in data.get("artifacts", [])}
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        if not action:
            continue
        aid = action.get("artifact_id", "")
        if not aid or aid not in art_ids:
            if action.get("type") == "RECEIVE_MESSAGE":
                # RECEIVE_MESSAGE always relates to the incoming invoice
                action["artifact_id"] = "art_invoice"
                node.setdefault("meta", {}).update(
                    _norm_meta("normalize_artifact_ref",
                               "RECEIVE_MESSAGE artifact_id defaulted to art_invoice")
                )
                log.append(f"  [ART] Node {node['id']!r} artifact_id set to 'art_invoice'")

    return data, log


# ===========================================================================
# Pass 2 — Canonical key uniqueness
# ===========================================================================

def fix_canonical_key_duplicates(data: dict) -> tuple[dict, list[str]]:
    """For every ``canonical_key`` that appears on more than one node:
    - Set ``meta.intent_key`` to the original key (if not already set).
    - Suffix ``meta.canonical_key`` with ``@<node_id>`` to make it unique.
    
    Nodes that already have a unique key only get ``intent_key`` set.
    
    Contract
    --------
    Pre:     ``data['nodes']`` exists.
    Post:    All ``canonical_key`` values unique; every node with ``canonical_key`` has ``intent_key``.
    Mutates: ``node.meta.canonical_key``, ``node.meta.intent_key``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []

    key_counts = Counter(
        (n.get("meta") or {}).get("canonical_key")
        for n in data.get("nodes", [])
        if (n.get("meta") or {}).get("canonical_key")
    )

    for node in data.get("nodes", []):
        meta = node.setdefault("meta", {})
        ckey = meta.get("canonical_key")
        if not ckey:
            continue

        # Always set intent_key (preserve original label for grouping)
        if "intent_key" not in meta:
            meta["intent_key"] = ckey

        if key_counts[ckey] > 1:
            # Only suffix if not already suffixed (idempotent)
            if "@" not in ckey:
                new_key = f"{ckey}@{node['id']}"
                meta["canonical_key"] = new_key
                log.append(
                    f"  [CKEY] {node['id']!r}: {ckey!r} -> {new_key!r}"
                )
        # else: unique key, just ensure intent_key is set (done above)

    return data, log


# ===========================================================================
# Pass 3 — Normalize edge conditions
# ===========================================================================

def normalize_edge_conditions(data: dict) -> tuple[dict, list[str]]:
    """Replace every edge condition string with its canonical DSL form.
    Conditions that cannot be normalised (e.g., IF_CONDITION) are left
    as-is so that later passes can detect and replace them.
    
    Contract
    --------
    Pre:     ``data['edges']`` exists.
    Post:    Every edge condition with a known synonym is replaced with canonical DSL form.
    Mutates: ``edge['condition']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    for idx, edge in enumerate(data.get("edges", [])):
        raw = edge.get("condition")
        if raw is None:
            continue
        norm = normalize_condition(raw)
        if norm is not None and norm != raw:
            log.append(
                f"  [COND] edge[{idx}] ({edge.get('frm')}->{edge.get('to')}): "
                f"{raw!r} -> {norm!r}"
            )
            edge["condition"] = norm
    return data, log


# ===========================================================================
# Pass 4 — Inject exception nodes
# ===========================================================================

def inject_exception_nodes(data: dict) -> tuple[dict, list[str]]:
    """Inject ``n_no_match`` and ``n_manual_review_gate`` nodes if absent.
    These are referenced by later passes when gateway branches need a
    fail-closed target.
    
    Contract
    --------
    Pre:     ``data['nodes']`` exists.
    Post:    ``n_no_match`` and ``n_manual_review_gate`` exist with correct action types.
    Mutates: ``data['nodes']`` (appends).
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    existing_ids = {n["id"] for n in data.get("nodes", [])}

    for nid, spec in _EXCEPTION_NODES.items():
        if nid not in existing_ids:
            data.setdefault("nodes", []).append(spec.copy())
            log.append(f"  [NODE] Injected exception node {nid!r}")
        else:
            log.append(f"  [NODE] {nid!r} already present")

    return data, log


# ===========================================================================
# Pass 5 — Fix MATCH_3_WAY gateway fan-out (n4)
# ===========================================================================

def fix_match3way_gateway(data: dict) -> tuple[dict, list[str]]:
    """Repair the MATCH_3_WAY gateway (node n4) — **only** if n4 is actually
    a MATCH_3_WAY gateway.
    
    Before: n4 has fan-out edges — multiple edges with normalized condition
            ``match_3_way == true``, plus one edge with un-normalizable
            condition SCHEDULE_PAYMENT.
    After:  n4 has exactly two mutually exclusive edges:
            - ``match_3_way == true``  -> n_threshold (existing)
            - ``match_3_way == false`` -> n_no_match  (added)
    
    Guard: If n4 is not a MATCH_3_WAY gateway (e.g. it is already
    ``task:VALIDATE_FIELDS``), this pass is a no-op.  The real MATCH_3_WAY
    gateway (typically n5) is handled by pass 5b instead.
    
    Contract
    --------
    Pre:     n4 may exist; guard skips if not MATCH_3_WAY.
    Post:    If n4 is MATCH_3_WAY: exactly 2 outgoing edges (MATCH/NO_MATCH); else no-op.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    GW = "n4"

    nodes_map = _node_by_id(data)
    if GW not in nodes_map:
        return data, log  # nothing to do

    # Guard: only operate if n4 is actually a MATCH_3_WAY gateway.
    # In the production source graph n4 is task:VALIDATE_FIELDS — the real
    # MATCH_3_WAY gateway is n5 (handled by pass 5b).
    if not _is_match3way_gateway(nodes_map[GW]):
        log.append(f"  [GW] {GW} is not a MATCH_3_WAY gateway — skipping pass 5")
        return data, log

    out_edges = _edges_from(data, GW)
    if not out_edges:
        return data, log

    # Determine desired edges (idempotent check)
    conditions = {normalize_condition(e.get("condition")) for e in out_edges}

    # Already correct: match_result-based 2-branch structure
    if (
        conditions == {'match_result == "MATCH"', 'match_result == "NO_MATCH"'}
        and len(out_edges) == 2
    ):
        log.append(f"  [GW] {GW} already has correct 2-branch structure")
        return data, log

    # Identify the approved target (first edge with match condition after
    # normalization that leads to n_threshold, or any match-true target)
    match_target = None
    for e in out_edges:
        norm_cond = normalize_condition(e.get("condition"))
        if norm_cond in ('match_result == "MATCH"', "match_3_way == true"):
            if match_target is None or e.get("to") == "n_threshold":
                match_target = e.get("to")

    if match_target is None:
        match_target = "n_threshold"  # fallback

    # Remove ALL existing outgoing edges from n4
    removed = _remove_edges(data, lambda e: e.get("frm") == GW)
    log.append(f"  [GW] {GW}: removed {removed} existing outgoing edge(s)")

    # Add exactly 2 new edges using match_result
    data["edges"].append(_norm_edge(
        GW, match_target, 'match_result == "MATCH"',
        "normalize_gateway_fanout"
    ))
    data["edges"].append(_norm_edge(
        GW, "n_no_match", 'match_result == "NO_MATCH"',
        "normalize_gateway_fanout"
    ))
    log.append(
        f"  [GW] {GW}: added edge -> {match_target} (match_result == \"MATCH\")"
    )
    log.append(
        f"  [GW] {GW}: added edge -> n_no_match (match_result == \"NO_MATCH\")"
    )

    return data, log


# ===========================================================================
# Pass 5b — Fix secondary MATCH_3_WAY gateways (e.g. n5)
# ===========================================================================

# Action types that are task-name labels, not routing conditions.  When these
# appear as the *condition* on an outgoing edge of a MATCH_3_WAY gateway, the
# miner placed the target task's action type in the condition field by mistake.
_NOISE_ACTION_TYPES = frozenset({
    "SCHEDULE_PAYMENT",
    "EXECUTE_PAYMENT",
    "APPROVE",
    "ROUTE_FOR_REVIEW",
})

_PATCH_ID_SECONDARY = "normalize_secondary_match_gateway"


def _find_chain_node(nodes_map: dict[str, dict], target_ids: set[str],
                     action_type: str) -> str | None:
    """

    Args:
      nodes_map: dict[str:
      dict]: 
      target_ids: set[str]:
      action_type: str:
      nodes_map: dict[str: 
      target_ids: set[str]: 
      action_type: str: 

    Returns:

    """
    for nid in target_ids:
        node = nodes_map.get(nid)
        if node and (node.get("action") or {}).get("type") == action_type:
            return nid
    return None


def fix_secondary_match_gateways(data: dict) -> tuple[dict, list[str]]:
    """Split secondary MATCH_3_WAY gateways (not n4) into task + decision gateway.
    
    The miner produces nodes that both *perform* the 3-way match and *branch*
    on its result.  This pass separates concerns:
    
    1. Convert the gateway into a **task** (``action.type = "MATCH_3_WAY"``).
       The task sets ``match_result`` in state.
    2. Inject a new **decision gateway** (``decision.type = "MATCH_DECISION"``)
       immediately after, whose only job is to branch on ``match_result``.
    3. Wire::
    
           task → decision                     (unconditional)
           decision → approve_target           (match_result == "MATCH")
           decision → n_no_match               (match_result == "NO_MATCH")
           decision → unmodeled_station        (match_result == "UNKNOWN")
    
    4. Ensure the sequential chain downstream of the MATCH branch::
    
           approve → schedule → execute        (all unconditional)
    
       If any chain node is missing, the MATCH branch is fail-closed to
       the unmodeled-gate station instead.
    
    Idempotent: after the first run the gateway is ``kind == "task"`` and
    ``_is_match3way_gateway`` no longer matches it.  A ``{gw_id}_decision``
    node existence check is a secondary guard.
    
    Contract
    --------
    Pre:     Secondary MATCH_3_WAY gateways may exist; requires exception stations.
    Post:    Each split into task + ``{id}_decision`` gateway with 3 canonical branches.
    Mutates: node ``kind/action/decision/meta``; ``data['nodes']``, ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    nodes_map = _node_by_id(data)

    # Collect secondary MATCH_3_WAY gateways (skip n4 — handled by pass 5)
    gateways = [
        n for n in data.get("nodes", [])
        if _is_match3way_gateway(n) and n["id"] != "n4"
    ]

    if not gateways:
        return data, log

    # Lazy station lookup — only if there's work to do
    no_match_id = _require_station(data, "task:MANUAL_REVIEW_MATCH_FAILED")
    unmodeled_id = _require_station(data, "task:MANUAL_REVIEW_UNMODELED_GATE")

    for gw in gateways:
        gw_id = gw["id"]
        decision_id = f"{gw_id}_decision"
        out_edges = _edges_from(data, gw_id)

        if not out_edges:
            continue

        # --- Idempotency: decision node already exists from a prior run ---
        if decision_id in nodes_map:
            log.append(f"  [GW2] {gw_id} already split — {decision_id} exists")
            continue

        # --- Phase 1A: collect all original targets for chain discovery ---
        original_targets: set[str] = {
            to for e in out_edges for to in [e.get("to")] if isinstance(to, str)
        }

        # --- Phase 1B: identify chain nodes ---
        approve_id = _find_chain_node(nodes_map, original_targets, "APPROVE")
        schedule_id = _find_chain_node(nodes_map, original_targets, "SCHEDULE_PAYMENT")
        execute_id = _find_chain_node(nodes_map, original_targets, "EXECUTE_PAYMENT")

        # Determine the MATCH branch head
        match_target: str | None = approve_id
        if match_target is None:
            # Fallback: first target with a MATCH-normalising condition
            for e in out_edges:
                if normalize_condition(e.get("condition")) == 'match_result == "MATCH"':
                    match_target = e.get("to")
                    break

        if match_target is None:
            log.append(
                f"  [GW2] {gw_id}: no MATCH branch target found — skipping "
                "(will be caught by unparseable-gateway pass)"
            )
            continue

        # --- Phase 1C: check chain completeness ---
        chain_complete = all((approve_id, schedule_id, execute_id))
        if not chain_complete:
            missing = []
            if not approve_id:
                missing.append("APPROVE")
            if not schedule_id:
                missing.append("SCHEDULE_PAYMENT")
            if not execute_id:
                missing.append("EXECUTE_PAYMENT")
            log.append(
                f"  [GW2] {gw_id}: incomplete chain — missing "
                f"{', '.join(missing)}; MATCH branch fail-closed to "
                f"{unmodeled_id}"
            )
            match_target = unmodeled_id

        # --- Phase 1D: convert gateway → task (MATCH_3_WAY) ---
        gw["kind"] = "task"
        gw["action"] = {
            "type":        "MATCH_3_WAY",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        }
        gw["decision"] = None
        gw.setdefault("meta", {}).update({
            **_norm_meta(_PATCH_ID_SECONDARY,
                         f"Gateway {gw_id} split: converted to task (MATCH_3_WAY)"),
            "synthetic": True,
            "semantic_assumption": "match_3way_task_decision_split",
            "origin_pass": "fix_secondary_match_gateways",
        })
        log.append(f"  [GW2] {gw_id}: converted gateway -> task (MATCH_3_WAY)")

        # --- Phase 1E: inject decision gateway ---
        decision_node: dict[str, Any] = {
            "id":       decision_id,
            "kind":     "gateway",
            "name":     f"Match Decision ({gw_id})",
            "action":   None,
            "decision": {"type": "MATCH_DECISION", "inputs": [], "expression": None},
            "evidence": [],
            "meta": {
                "canonical_key": f"gw:MATCH_DECISION@{decision_id}",
                "intent_key":    "gw:MATCH_DECISION",
                **_norm_meta(_PATCH_ID_SECONDARY,
                             f"Decision gateway split from {gw_id}"),
                "synthetic": True,
                "semantic_assumption": "match_3way_task_decision_split",
                "origin_pass": "fix_secondary_match_gateways",
            },
        }
        data["nodes"].append(decision_node)
        log.append(f"  [GW2] {gw_id}: injected decision gateway {decision_id}")

        # --- Phase 1F: remove ALL existing outgoing edges from task ---
        removed = _remove_edges(data, lambda e: e.get("frm") == gw_id)
        log.append(f"  [GW2] {gw_id}: removed {removed} existing outgoing edge(s)")

        # --- Phase 1G: wire task → decision (unconditional) ---
        data["edges"].append(
            _norm_edge(gw_id, decision_id, None, _PATCH_ID_SECONDARY)
        )
        log.append(f"  [GW2] {gw_id}: wired {gw_id}->{decision_id} (unconditional)")

        # --- Phase 1H: wire decision → branches ---
        data["edges"].append(
            _norm_edge(decision_id, match_target, 'match_result == "MATCH"', _PATCH_ID_SECONDARY)
        )
        data["edges"].append(
            _norm_edge(decision_id, no_match_id, 'match_result == "NO_MATCH"', _PATCH_ID_SECONDARY)
        )
        data["edges"].append(
            _norm_edge(decision_id, unmodeled_id, 'match_result == "UNKNOWN"', _PATCH_ID_SECONDARY)
        )
        log.append(f'  [GW2] {gw_id}: {decision_id} -> {match_target} (match_result == "MATCH")')
        log.append(f'  [GW2] {gw_id}: {decision_id} -> {no_match_id} (match_result == "NO_MATCH")')
        log.append(f'  [GW2] {gw_id}: {decision_id} -> {unmodeled_id} (match_result == "UNKNOWN")')

        # --- Phase 2: wire sequential chain (approve → schedule → execute) ---
        if chain_complete:
            assert approve_id and schedule_id and execute_id  # for type checker
            chain_links = [
                (approve_id, schedule_id),
                (schedule_id, execute_id),
            ]
            for frm, to in chain_links:
                if not _has_edge(data, frm, to):
                    data["edges"].append(
                        _norm_edge(frm, to, None, _PATCH_ID_SECONDARY)
                    )
                    log.append(f"  [GW2] {gw_id}: wired chain {frm}->{to}")
                else:
                    log.append(f"  [GW2] {gw_id}: chain {frm}->{to} already present")

    return data, log


# ===========================================================================
# Pass 6 — Fix main execution path terminus (n7 -> end)
# ===========================================================================

def fix_main_execution_path(data: dict) -> tuple[dict, list[str]]:
    """The mined graph wires EXECUTE_PAYMENT (n7) -> HAS_PO gateway (n8).
    After payment is executed the process should end.  Change n7 -> n32.
    
    Contract
    --------
    Pre:     n7/n8 may exist.
    Post:    No edge n7→n8; if n7 exists and had n8 edge, edge n7→end exists.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    end_id = _end_node_id(data)
    if not end_id:
        log.append("  [PATH] No end node found — skipping n7 path fix")
        return data, log

    n7_to_n8 = [
        e for e in data.get("edges", [])
        if e.get("frm") == "n7" and e.get("to") == "n8"
    ]

    if not n7_to_n8:
        # Already fixed or not present
        if _has_edge(data, "n7", end_id):
            log.append(f"  [PATH] n7->{end_id} already wired")
        return data, log

    # Remove n7->n8
    _remove_edges(data, lambda e: e.get("frm") == "n7" and e.get("to") == "n8")
    log.append("  [PATH] Removed n7->n8 (payment should end the process)")

    # Add n7->end_id
    if not _has_edge(data, "n7", end_id):
        data["edges"].append(
            _norm_edge("n7", end_id, None, "normalize_execution_path")
        )
        log.append(f"  [PATH] Added n7->{end_id} (end of main execution)")

    return data, log


# ===========================================================================
# Pass 7 — Fix HAS_PO gateway fan-out (n8)
# ===========================================================================

def fix_haspo_gateway(data: dict) -> tuple[dict, list[str]]:
    """Repair the HAS_PO gateway (n8).
    
    Before: n8 has 6 fan-out edges all with condition ``has_po == true``
            pointing to sequential steps n9..n14.
    After:
      - n8 -> n9   (has_po == false)  route-for-review when NO PO
      - n8 -> n15  (has_po == true)   proceed to matching when HAS PO
      - Sequential chain n9->n10->n11->n12->end_id  (no-PO approval path)
      - Remove n14->n15 loop edge (prevents unwanted re-entry to match)
    
    Contract
    --------
    Pre:     n8 may be HAS_PO gateway.
    Post:    n8 has exactly 2 edges: ``has_po==true``→n15, ``has_po==false``→n9; chain n9→n10→n11→n12.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    GW = "n8"
    end_id = _end_node_id(data)

    nodes_map = _node_by_id(data)
    if GW not in nodes_map:
        return data, log

    out_edges = _edges_from(data, GW)
    if not out_edges:
        return data, log

    # Idempotency check: already exactly 2 exclusive branches
    conditions = {normalize_condition(e.get("condition")) for e in out_edges}
    if (
        conditions == {"has_po == true", "has_po == false"}
        and len(out_edges) == 2
    ):
        log.append(f"  [GW] {GW} already has correct 2-branch structure")
        return data, log

    # Remove all outgoing edges from n8
    removed = _remove_edges(data, lambda e: e.get("frm") == GW)
    log.append(f"  [GW] {GW}: removed {removed} fan-out edge(s)")

    # Add 2-branch structure
    data["edges"].append(
        _norm_edge(GW, "n9", "has_po == false", "normalize_haspo_gateway")
    )
    data["edges"].append(
        _norm_edge(GW, "n15", "has_po == true", "normalize_haspo_gateway")
    )
    log.append(f"  [GW] {GW}: added n9 (has_po == false) and n15 (has_po == true)")

    # Build sequential chain for no-PO approval path: n9->n10->n11->n12->end
    chain = [("n9", "n10"), ("n10", "n11"), ("n11", "n12")]
    for frm, to in chain:
        if not _has_edge(data, frm, to):
            data["edges"].append(
                _norm_edge(frm, to, None, "normalize_haspo_gateway")
            )
            log.append(f"  [GW] Added sequential edge {frm}->{to}")

    if end_id and not _has_edge(data, "n12", end_id):
        data["edges"].append(
            _norm_edge("n12", end_id, None, "normalize_haspo_gateway")
        )
        log.append(f"  [GW] Added n12->{end_id} (end of no-PO approval path)")

    # Remove n14->n15 loop (n14=UPDATE_STATUS should not loop back to matching)
    removed_loop = _remove_edges(
        data, lambda e: e.get("frm") == "n14" and e.get("to") == "n15"
    )
    if removed_loop:
        log.append(f"  [GW] Removed n14->n15 loop edge")

    return data, log


# ===========================================================================
# Pass 8 — Fix placeholder gateways (IF_CONDITION, SCHEDULE_PAYMENT edges)
# ===========================================================================

# Map: gateway node id -> fix strategy
# "exception" : convert gateway to task, route to n_manual_review_gate
# "explicit"  : replace edges with explicit DSL conditions
_PLACEHOLDER_GATEWAY_STRATEGY: dict[str, str] = {
    "n16": "exception",   # variance tolerance — unmodeled, fail closed
    "n21": "exception",   # GL account code    — unmodeled, fail closed
    "n28": "explicit",    # duplicate check    — status == "DUPLICATE" is derivable
}


def fix_placeholder_gateways(data: dict) -> tuple[dict, list[str]]:
    """Replace placeholder gateway conditions with explicit DSL or exception routing.
    
    * n16 / n21 (IF_CONDITION, unmodeled): convert node kind from "gateway"
      to "task" with intent MANUAL_REVIEW_UNMODELED_GATE; remove all
      outgoing edges; add single edge to n_manual_review_gate.
    
    * n28 (duplicate check): keep as gateway but replace IF_CONDITION edges
      with ``status == "DUPLICATE"`` / ``status != "DUPLICATE"``; remove
      the erroneous MATCH_3_WAY edge; add n30->n31 sequential wiring.
    
    Contract
    --------
    Pre:     n16/n21/n28 may exist with placeholder conditions.
    Post:    n16/n21 → exception tasks; n28 → ``status=="DUPLICATE"`` / ``status!="DUPLICATE"``.
    Mutates: node ``kind/action/decision/meta``; ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    nodes_map = _node_by_id(data)

    for gw_id, strategy in _PLACEHOLDER_GATEWAY_STRATEGY.items():
        node = nodes_map.get(gw_id)
        if node is None:
            continue

        if strategy == "exception":
            _fix_gateway_to_exception(data, node, gw_id, log)
        elif strategy == "explicit":
            _fix_gateway_explicit_n28(data, node, gw_id, log)

    return data, log


def _fix_gateway_to_exception(
    data: dict, node: dict, gw_id: str, log: list[str]
) -> None:
    """Convert a gateway with unmodeled conditions into a manual-review task.

    Args:
      data: dict:
      node: dict:
      gw_id: str:
      log: list[str]:
      data: dict: 
      node: dict: 
      gw_id: str: 
      log: list[str]: 

    Returns:

    """

    # Idempotency: already converted?
    if node.get("kind") == "task" and (
        (node.get("action") or {}).get("type") == "MANUAL_REVIEW_UNMODELED_GATE"
    ):
        log.append(f"  [PGW] {gw_id} already converted to exception task")
        return

    # Change gateway -> task
    node["kind"]     = "task"
    node["action"]   = {
        "type":        "MANUAL_REVIEW_UNMODELED_GATE",
        "actor_id":    "role_ap_clerk",
        "artifact_id": "art_invoice",
        "extra":       {},
    }
    node["decision"] = None
    node.setdefault("meta", {}).update(
        _norm_meta(
            "normalize_placeholder_gateways",
            f"Gateway {gw_id} has unmodeled IF_CONDITION; routed to manual review",
        )
    )
    log.append(f"  [PGW] {gw_id}: converted gateway -> task (MANUAL_REVIEW_UNMODELED_GATE)")

    # Remove all old outgoing edges
    removed = _remove_edges(data, lambda e: e.get("frm") == gw_id)
    log.append(f"  [PGW] {gw_id}: removed {removed} outgoing edge(s)")

    # Add single edge to manual_review_gate (task -> single target = unconditional)
    if not _has_edge(data, gw_id, "n_manual_review_gate"):
        data["edges"].append(
            _norm_edge(gw_id, "n_manual_review_gate", None,
                       "normalize_placeholder_gateways")
        )
        log.append(f"  [PGW] {gw_id}: added edge -> n_manual_review_gate")


def _fix_gateway_explicit_n28(
    data: dict, node: dict, gw_id: str, log: list[str]
) -> None:
    """Fix the duplicate-check gateway (n28) with explicit status-based conditions.
    
    Before:  n28 -> n29 (IF_CONDITION)
             n28 -> n30 (IF_CONDITION)
             n28 -> n31 (MATCH_3_WAY — erroneous; n31 should follow n30)
    After:   n28 -> n29 (status == "DUPLICATE")
             n28 -> n30 (status != "DUPLICATE")
             n30 -> n31 (null — sequential)

    Args:
      data: dict:
      node: dict:
      gw_id: str:
      log: list[str]:
      data: dict: 
      node: dict: 
      gw_id: str: 
      log: list[str]: 

    Returns:

    """
    out_edges = _edges_from(data, gw_id)

    # Idempotency check
    conditions = {normalize_condition(e.get("condition")) for e in out_edges}
    if conditions == {'status == "DUPLICATE"', 'status != "DUPLICATE"'}:
        log.append(f"  [PGW] {gw_id} already has explicit duplicate conditions")
        return

    # Remove all outgoing edges from n28
    removed = _remove_edges(data, lambda e: e.get("frm") == gw_id)
    log.append(f"  [PGW] {gw_id}: removed {removed} edge(s)")

    # Add 2 explicit branches
    data["edges"].append(
        _norm_edge(gw_id, "n29", 'status == "DUPLICATE"',
                   "normalize_duplicate_gateway")
    )
    data["edges"].append(
        _norm_edge(gw_id, "n30", 'status != "DUPLICATE"',
                   "normalize_duplicate_gateway")
    )
    log.append(f'  [PGW] {gw_id}: added n29 (status == "DUPLICATE")')
    log.append(f'  [PGW] {gw_id}: added n30 (status != "DUPLICATE")')

    # Wire n30 -> n31 sequentially (if not already present)
    if not _has_edge(data, "n30", "n31"):
        data["edges"].append(
            _norm_edge("n30", "n31", None, "normalize_duplicate_gateway")
        )
        log.append("  [PGW] Added sequential edge n30->n31")

    # Record synthetic edge metadata on the source node
    node.setdefault("meta", {})["synthetic_edges"] = [
        {
            "to": "n29",
            "condition": 'status == "DUPLICATE"',
            "semantic_assumption": "duplicate_check_derivable",
            "origin_pass": "fix_placeholder_gateways",
        },
        {
            "to": "n30",
            "condition": 'status != "DUPLICATE"',
            "semantic_assumption": "duplicate_check_derivable",
            "origin_pass": "fix_placeholder_gateways",
        },
    ]


# ===========================================================================
# Pass 9 — Convert unparseable gateways to exception station
# ===========================================================================

def _require_station(data: dict, intent_key: str) -> str:
    """

    Args:
      data: dict:
      intent_key: str:
      data: dict: 
      intent_key: str: 

    Returns:

    """
    for node in data.get("nodes", []):
        meta = node.get("meta") or {}
        ik = meta.get("intent_key") or meta.get("canonical_key", "")
        if ik == intent_key:
            return node["id"]
    raise ValueError(
        f"Required station {intent_key!r} not found in graph. "
        "Ensure inject_exception_nodes() or patch_logic.inject_exception_stations() "
        "has run before this pass."
    )


# Gateway decision types that have dedicated repair passes upstream.
# If a gateway has one of these types AND at least one parseable outgoing
# condition, we skip conversion — the dedicated pass will handle it.
# This prevents false positives where miner-label noise (e.g. a
# "SCHEDULE_PAYMENT" condition on a MATCH_3_WAY gateway) would cause
# premature conversion before the dedicated pass runs.
_KNOWN_STRUCTURED_GATEWAY_TYPES = frozenset({
    "MATCH_3_WAY",
    "MATCH_DECISION",
    "HAS_PO",
    "APPROVE_OR_REJECT",
    "THRESHOLD_AMOUNT_10K",
})


def convert_unparseable_gateways_to_station(data: dict) -> tuple[dict, list[str]]:
    """Convert any remaining gateway with unparseable edge conditions into a
    manual-review task routed to the unmodeled-gate exception station.
    
    A gateway is unparseable if *any* of its outgoing edges has a condition
    that ``normalize_condition()`` maps to ``None`` (e.g. ``IF_CONDITION``).
    
    **Exception**: known structured gateways (MATCH_3_WAY, HAS_PO, etc.)
    that have at least one parseable outgoing condition are skipped — their
    dedicated repair passes handle the noise edges.  Only convert if *all*
    outgoing conditions normalise to None, or the gateway is not a known
    structured type.
    
    Repair:
    1. Change ``node.kind`` from ``"gateway"`` to ``"task"``.
    2. Set ``action.type = "MANUAL_REVIEW_UNMODELED_GATE"``.
    3. Remove all outgoing edges.
    4. Add one unconditional edge to the unmodeled-gate station.
    
    Idempotent: already-converted nodes (kind != "gateway") are skipped.
    
    Contract
    --------
    Pre:     Gateways with unparseable conditions may remain.
    Post:    No gateway has all-unparseable conditions (unless known structured with some parseable).
    Mutates: node ``kind/action/decision/meta``; ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []

    station_id = _require_station(data, "task:MANUAL_REVIEW_UNMODELED_GATE")

    nodes_map = _node_by_id(data)
    converted: list[str] = []

    for node in data.get("nodes", []):
        if node.get("kind") != "gateway":
            continue

        nid = node["id"]
        out_edges = _edges_from(data, nid)
        if not out_edges:
            continue

        # Classify outgoing conditions
        has_unparseable = False
        has_parseable = False
        for e in out_edges:
            cond = e.get("condition")
            if cond is not None and normalize_condition(cond) is None:
                has_unparseable = True
            elif cond is not None and normalize_condition(cond) is not None:
                has_parseable = True

        if not has_unparseable:
            continue

        # Known structured gateways with at least one parseable condition
        # are left for their dedicated repair passes (e.g. fix_match3way_gateway).
        gw_type = ((node.get("decision") or {}).get("type") or "").upper()
        if gw_type in _KNOWN_STRUCTURED_GATEWAY_TYPES and has_parseable:
            log.append(
                f"  [UNPARSE] {nid}: skipped — known structured gateway "
                f"({gw_type}) with parseable conditions"
            )
            continue

        # Convert gateway → task
        node["kind"] = "task"
        node["action"] = {
            "type":        "MANUAL_REVIEW_UNMODELED_GATE",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        }
        node["decision"] = None
        node.setdefault("meta", {}).update({
            **_norm_meta(
                "normalize_unparseable_gateway",
                f"Gateway {nid} has unparseable condition(s); routed to manual review",
            ),
            "synthetic": True,
            "semantic_assumption": "fail_closed_unmodeled",
            "origin_pass": "convert_unparseable_gateways_to_station",
        })
        log.append(
            f"  [UNPARSE] {nid}: converted gateway -> task "
            f"(MANUAL_REVIEW_UNMODELED_GATE)"
        )

        # Remove all outgoing edges
        removed = _remove_edges(data, lambda e: e.get("frm") == nid)
        log.append(f"  [UNPARSE] {nid}: removed {removed} outgoing edge(s)")

        # Add single unconditional edge to station
        if not _has_edge(data, nid, station_id):
            data["edges"].append({
                "frm":       nid,
                "to":        station_id,
                "condition": None,
                "meta":      _norm_meta(
                    "normalize_unparseable_gateway",
                    f"Fail-closed: {nid} unparseable gateway -> {station_id}",
                ),
            })
            log.append(f"  [UNPARSE] {nid}: added edge -> {station_id}")

        converted.append(nid)

    return data, log


# ===========================================================================
# Pass 10 — Convert whitelisted fan-out gateways to sequential dispatch
# ===========================================================================

# Gateways with these intent_keys / canonical_keys are eligible for
# sequential dispatch instead of the ambiguous-route catch-all.
_SEQUENTIAL_DISPATCH_WHITELIST = frozenset({
    "gw:HAS_PO",
    "gw:APPROVE_OR_REJECT",
})

# Stable ordering priority for action types in sequential chains.
# Lower number = earlier in chain.  Unknown types sort last (by alpha).
_DISPATCH_PRIORITY: dict[str, int] = {
    "ROUTE_FOR_REVIEW":               10,
    "REVIEW":                         20,
    "UPDATE_RECORD":                  30,
    "APPROVE":                        40,
    "SCHEDULE_PAYMENT":               50,
    "EXECUTE_PAYMENT":                60,
    "NOTIFY":                         70,
    "UPDATE_STATUS":                  80,
    "MANUAL_REVIEW_NO_PO":            90,
    "MANUAL_REVIEW_MATCH_FAILED":     91,
    "MANUAL_REVIEW_UNMODELED_GATE":   92,
    "MANUAL_REVIEW_AMBIGUOUS_ROUTE":  93,
}


def _dispatch_sort_key(node: dict) -> tuple[int, str]:
    """Sort key for deterministic chain ordering: (priority, node_id).

    Args:
      node: dict:
      node: dict: 

    Returns:

    """
    atype = (node.get("action") or {}).get("type", "")
    return (_DISPATCH_PRIORITY.get(atype, 999), node["id"])


def convert_whitelisted_fanout_to_sequential(data: dict) -> tuple[dict, list[str]]:
    """Convert whitelisted fan-out gateways into SEQUENTIAL_DISPATCH tasks
    with a deterministic chain of their original targets.
    
    Detection: gateway with intent_key/canonical_key in whitelist, whose
    outgoing edges include 3+ with the same normalized condition, and all
    targets in that fan-out group are tasks (kind='task').
    
    Repair:
      - Convert gateway kind → 'task', action.type → 'SEQUENTIAL_DISPATCH'.
      - Remove all outgoing edges from gateway.
      - Remove inter-target edges (edges between any two targets in the
        fan-out group) to avoid routing ambiguity with the new chain.
      - Add unconditional chain: gateway → T1 → T2 → … → Tn (sorted by
        action.type priority, then node id).
    
    Idempotent: already-converted nodes (kind != 'gateway') are skipped.
    
    Contract
    --------
    Pre:     Whitelisted gateways may have 3+ fan-out.
    Post:    Converted to SEQUENTIAL_DISPATCH with deterministic chain; no inter-target edges.
    Mutates: node ``kind/action/decision/meta``; ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    nodes_map = _node_by_id(data)

    for node in data.get("nodes", []):
        if node.get("kind") != "gateway":
            continue

        meta = node.get("meta") or {}
        ik = meta.get("intent_key") or meta.get("canonical_key", "")
        if ik not in _SEQUENTIAL_DISPATCH_WHITELIST:
            continue

        nid = node["id"]
        out_edges = _edges_from(data, nid)

        # Group outgoing edges by normalized condition
        cond_groups: dict[str | None, list[dict]] = {}
        for e in out_edges:
            norm = normalize_condition(e.get("condition"))
            cond_groups.setdefault(norm, []).append(e)

        # Find the largest fan-out group (3+ edges, same condition)
        fanout_group: list[dict] = []
        fanout_cond: str | None = None
        for cond, edges in cond_groups.items():
            if len(edges) >= 3 and len(edges) > len(fanout_group):
                fanout_group = edges
                fanout_cond = cond

        if len(fanout_group) < 3:
            continue

        # Collect targets and verify all are tasks
        target_ids = [e.get("to") for e in fanout_group]
        targets = [nodes_map[tid] for tid in target_ids if tid in nodes_map]
        if not all(t.get("kind") == "task" for t in targets):
            continue

        # Sort targets by deterministic priority
        targets.sort(key=_dispatch_sort_key)
        sorted_ids = [t["id"] for t in targets]

        log.append(
            f"  [SEQ] {nid} ({ik}): converting fan-out gateway -> "
            f"SEQUENTIAL_DISPATCH chain {sorted_ids}"
        )

        # Convert gateway → task
        node["kind"] = "task"
        node["action"] = {
            "type":        "SEQUENTIAL_DISPATCH",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {
                "dispatch_condition": fanout_cond,
                "chain": sorted_ids,
            },
        }
        node["decision"] = None

        # Build descriptive rationale with removed edges and ordering rule
        removed_desc = ", ".join(
            f"{e.get('frm')}->{e.get('to')} [{e.get('condition')}]"
            for e in fanout_group
        )
        node.setdefault("meta", {}).update({
            **_norm_meta(
                "normalize_sequential_dispatch",
                f"Gateway {nid} ({ik}) had {len(fanout_group)} fan-out edges "
                f"(condition={fanout_cond!r}) targeting tasks "
                f"{[e.get('to') for e in fanout_group]}. "
                f"Converted to sequential dispatch chain "
                f"{' -> '.join(sorted_ids)} "
                f"(ordered by action.type priority, then node id). "
                f"Removed edges: {removed_desc}",
            ),
            "synthetic": True,
            "semantic_assumption": "do_all_sequential",
            "origin_pass": "convert_whitelisted_fanout_to_sequential",
        })

        # Remove ALL outgoing edges from the gateway
        removed_gw = _remove_edges(data, lambda e: e.get("frm") == nid)
        log.append(f"  [SEQ] {nid}: removed {removed_gw} outgoing edge(s)")

        # Remove inter-target edges (edges between any two targets)
        target_set = set(sorted_ids)
        removed_inter = _remove_edges(
            data,
            lambda e: e.get("frm") in target_set and e.get("to") in target_set,
        )
        if removed_inter:
            log.append(
                f"  [SEQ] {nid}: removed {removed_inter} inter-target edge(s)"
            )

        # Add unconditional chain: gateway → T1 → T2 → … → Tn
        chain_pairs = [(nid, sorted_ids[0])]
        for i in range(len(sorted_ids) - 1):
            chain_pairs.append((sorted_ids[i], sorted_ids[i + 1]))

        for frm, to in chain_pairs:
            data["edges"].append(
                _norm_edge(frm, to, None, "normalize_sequential_dispatch")
            )
            log.append(f"  [SEQ] Added chain edge {frm} -> {to}")

    return data, log


# ===========================================================================
# Pass 11 — Convert fan-out gateways to ambiguous-route station
# ===========================================================================

def convert_fanout_gateways_to_ambiguous_station(data: dict) -> tuple[dict, list[str]]:
    """Convert any remaining gateway with fan-out edges (multiple edges sharing
    the same normalized condition) into a manual-review task routed to the
    ambiguous-route exception station.
    
    Detection: group outgoing edges by ``normalize_condition(cond)``; if any
    group has size > 1, the gateway is fan-out misuse (parallel dispatch
    masquerading as a branch).
    
    Repair is identical to ``convert_unparseable_gateways_to_station`` but
    targets ``task:MANUAL_REVIEW_AMBIGUOUS_ROUTE`` instead.
    
    Idempotent: already-converted nodes (kind != "gateway") are skipped.
    The station is only required if a fan-out gateway is actually detected.
    
    Contract
    --------
    Pre:     Remaining gateways may have fan-out (same condition, multiple targets).
    Post:    No gateway has fan-out edges.
    Mutates: node ``kind/action/decision/meta``; ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []

    # Phase 1: Collect gateways that need conversion before requiring the
    # station, so graphs without fan-out gateways don't fail on a missing
    # station.
    gateways_to_convert: list[dict] = []
    for node in data.get("nodes", []):
        if node.get("kind") != "gateway":
            continue

        out_edges = _edges_from(data, node["id"])
        if len(out_edges) < 2:
            continue

        # Group edges by normalized condition
        cond_counts: dict[str | None, int] = {}
        for e in out_edges:
            norm = normalize_condition(e.get("condition"))
            cond_counts[norm] = cond_counts.get(norm, 0) + 1

        if any(c > 1 for c in cond_counts.values()):
            gateways_to_convert.append(node)

    if not gateways_to_convert:
        return data, log

    # Phase 2: Require station only when we actually have work to do
    station_id = _require_station(data, "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE")

    for node in gateways_to_convert:
        nid = node["id"]

        # Convert gateway → task
        node["kind"] = "task"
        node["action"] = {
            "type":        "MANUAL_REVIEW_AMBIGUOUS_ROUTE",
            "actor_id":    "role_ap_clerk",
            "artifact_id": "art_invoice",
            "extra":       {},
        }
        node["decision"] = None
        node.setdefault("meta", {}).update({
            **_norm_meta(
                "normalize_fanout_gateway",
                f"Gateway {nid} has fan-out edges (same condition, multiple targets); "
                f"routed to ambiguous-route station",
            ),
            "synthetic": True,
            "semantic_assumption": "fail_closed_ambiguous",
            "origin_pass": "convert_fanout_gateways_to_ambiguous_station",
        })
        log.append(
            f"  [FANOUT] {nid}: converted gateway -> task "
            f"(MANUAL_REVIEW_AMBIGUOUS_ROUTE)"
        )

        # Remove all outgoing edges
        removed = _remove_edges(data, lambda e: e.get("frm") == nid)
        log.append(f"  [FANOUT] {nid}: removed {removed} outgoing edge(s)")

        # Add single unconditional edge to station
        if not _has_edge(data, nid, station_id):
            data["edges"].append({
                "frm":       nid,
                "to":        station_id,
                "condition": None,
                "meta":      _norm_meta(
                    "normalize_fanout_gateway",
                    f"Fail-closed: {nid} fan-out gateway -> {station_id}",
                ),
            })
            log.append(f"  [FANOUT] {nid}: added edge -> {station_id}")

    return data, log


# ===========================================================================
# Pass 11 — Wire BAD_EXTRACTION route from ENTER_RECORD to rejection node
# ===========================================================================

def wire_bad_extraction_route(data: dict) -> tuple[dict, list[str]]:
    """Inject a conditional edge from the ENTER_RECORD node to the rejection
    node so that ``status == "BAD_EXTRACTION"`` routes deterministically
    to reject instead of falling through to VALIDATE_FIELDS.
    
    1. Find ENTER_RECORD node by ``action.type == "ENTER_RECORD"``.
    2. Find rejection node by ``action.type in {"REJECT_INVOICE", "REJECT"}``,
       preferring ``REJECT_INVOICE``.
    3. Inject edge with condition ``status == "BAD_EXTRACTION"`` (canonical DSL).
    4. Ensure the conditional edge appears before any unconditional edge from
       the same source (defense-in-depth; the router already evaluates
       conditional edges before unconditional fallback).
    
    Contract
    --------
    Pre:     ENTER_RECORD and rejection nodes may exist.
    Post:    Conditional edge ``status=="BAD_EXTRACTION"`` from ENTER_RECORD to rejection.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []

    # Find ENTER_RECORD node
    enter_id: str | None = None
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        if action.get("type") == "ENTER_RECORD":
            enter_id = node["id"]
            break

    if enter_id is None:
        log.append("  [BAD_EXT] No ENTER_RECORD node found — skipping")
        return data, log

    # Find rejection node (prefer REJECT_INVOICE over REJECT)
    reject_id: str | None = None
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        atype = action.get("type", "")
        if atype == "REJECT_INVOICE":
            reject_id = node["id"]
            break
        if atype == "REJECT" and reject_id is None:
            reject_id = node["id"]

    if reject_id is None:
        log.append("  [BAD_EXT] No rejection node found — skipping")
        return data, log

    # Idempotency: check if edge already exists
    condition = 'status == "BAD_EXTRACTION"'
    for edge in data.get("edges", []):
        if (
            edge.get("frm") == enter_id
            and edge.get("to") == reject_id
            and edge.get("condition") == condition
        ):
            log.append(
                f"  [BAD_EXT] Edge {enter_id}->{reject_id} "
                f"(condition={condition!r}) already present"
            )
            return data, log

    # Build the new conditional edge
    new_edge = _norm_edge(
        enter_id, reject_id, condition,
        "normalize_bad_extraction_route",
    )

    # Insert BEFORE any unconditional edge from the same source (defense-in-depth)
    insert_idx = len(data["edges"])  # default: append at end
    for idx, edge in enumerate(data["edges"]):
        if edge.get("frm") == enter_id and edge.get("condition") is None:
            insert_idx = idx
            break

    data["edges"].insert(insert_idx, new_edge)
    log.append(
        f"  [BAD_EXT] Injected edge {enter_id}->{reject_id} "
        f"(condition={condition!r}) at index {insert_idx}"
    )

    return data, log


# ===========================================================================
# Pass 12 — Wire CRITIC_RETRY route from ENTER_RECORD
# ===========================================================================

def wire_critic_retry_route(data: dict) -> tuple[dict, list[str]]:
    """Replace the simple ``BAD_EXTRACTION`` → reject edge with a two-path
    routing through the CRITIC_RETRY node.
    
    After this pass, ENTER_RECORD routes:
    - ``status == "NEEDS_RETRY"``     → n_critic_retry
    - ``status == "BAD_EXTRACTION"``  → n_exc_bad_extraction
    
    And n_critic_retry routes:
    - ``status == "BAD_EXTRACTION"``  → n_exc_bad_extraction
    - ``has_po == false`` (guarded)   → n_exception  (no-PO guard)
    - unconditional fallback          → n4           (success path)
    
    Contract
    --------
    Pre:     ``wire_bad_extraction_route`` has already injected the
             ``status == "BAD_EXTRACTION"`` edge from ENTER_RECORD to reject.
    Post:    That edge is replaced; critic retry edges are wired.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    _PATCH_ID = "normalize_critic_retry_route"

    # --- Find required nodes -------------------------------------------------

    # ENTER_RECORD
    enter_id: str | None = None
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        if action.get("type") == "ENTER_RECORD":
            enter_id = node["id"]
            break

    if enter_id is None:
        log.append("  [CRITIC_RETRY] No ENTER_RECORD node found — skipping")
        return data, log

    # CRITIC_RETRY node
    critic_id: str | None = None
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        if action.get("type") == "CRITIC_RETRY":
            critic_id = node["id"]
            break

    if critic_id is None:
        log.append("  [CRITIC_RETRY] No CRITIC_RETRY node found — skipping")
        return data, log

    # Exception station for bad extraction
    exc_id: str | None = None
    for node in data.get("nodes", []):
        meta = node.get("meta") or {}
        ik = meta.get("intent_key") or meta.get("canonical_key", "")
        if ik == "task:MANUAL_REVIEW_BAD_EXTRACTION":
            exc_id = node["id"]
            break

    if exc_id is None:
        log.append("  [CRITIC_RETRY] No BAD_EXTRACTION exception station found — skipping")
        return data, log

    # No-PO exception node (MANUAL_REVIEW_NO_PO)
    nopo_id: str | None = None
    for node in data.get("nodes", []):
        action = node.get("action") or {}
        if action.get("type") == "MANUAL_REVIEW_NO_PO":
            nopo_id = node["id"]
            break

    # Find the unconditional fallback target from ENTER_RECORD (n4)
    fallback_target: str | None = None
    for edge in data.get("edges", []):
        if edge.get("frm") == enter_id and edge.get("condition") is None:
            fallback_target = edge.get("to")
            break

    if fallback_target is None:
        log.append("  [CRITIC_RETRY] No unconditional fallback edge from ENTER_RECORD — skipping")
        return data, log

    # --- Idempotency check ---------------------------------------------------
    needs_retry_cond = 'status == "NEEDS_RETRY"'
    for edge in data.get("edges", []):
        if (
            edge.get("frm") == enter_id
            and edge.get("to") == critic_id
            and edge.get("condition") == needs_retry_cond
        ):
            log.append(
                f"  [CRITIC_RETRY] Edge {enter_id}->{critic_id} "
                f"(condition={needs_retry_cond!r}) already present — skipping"
            )
            return data, log

    # --- Step A: Remove old BAD_EXTRACTION → reject edge from ENTER_RECORD ---
    old_cond = 'status == "BAD_EXTRACTION"'
    removed = _remove_edges(data, lambda e: (
        e.get("frm") == enter_id
        and e.get("condition") == old_cond
    ))
    if removed:
        log.append(
            f"  [CRITIC_RETRY] Removed {removed} old BAD_EXTRACTION edge(s) from {enter_id}"
        )

    # Insert new edges from ENTER_RECORD (before unconditional fallback)
    insert_idx = len(data["edges"])
    for idx, edge in enumerate(data["edges"]):
        if edge.get("frm") == enter_id and edge.get("condition") is None:
            insert_idx = idx
            break

    # n3 → n_critic_retry: status == "NEEDS_RETRY"
    data["edges"].insert(insert_idx, _norm_edge(
        enter_id, critic_id, needs_retry_cond, _PATCH_ID,
    ))
    log.append(
        f"  [CRITIC_RETRY] Injected {enter_id}->{critic_id} "
        f"(condition={needs_retry_cond!r})"
    )

    # n3 → n_exc_bad_extraction: status == "BAD_EXTRACTION"
    data["edges"].insert(insert_idx + 1, _norm_edge(
        enter_id, exc_id, old_cond, _PATCH_ID,
    ))
    log.append(
        f"  [CRITIC_RETRY] Injected {enter_id}->{exc_id} "
        f"(condition={old_cond!r})"
    )

    # --- Step B: Add edges from n_critic_retry --------------------------------

    # critic → exc_bad_extraction: status == "BAD_EXTRACTION"
    if not any(
        e.get("frm") == critic_id and e.get("to") == exc_id
        for e in data.get("edges", [])
    ):
        data["edges"].append(_norm_edge(
            critic_id, exc_id, old_cond, _PATCH_ID,
        ))
        log.append(
            f"  [CRITIC_RETRY] Injected {critic_id}->{exc_id} "
            f"(condition={old_cond!r})"
        )

    # critic → n_exception: no-PO guard (mirrors n3's pattern)
    if nopo_id is not None:
        nopo_cond = 'status != "BAD_EXTRACTION" AND has_po == false'
        if not any(
            e.get("frm") == critic_id and e.get("to") == nopo_id
            for e in data.get("edges", [])
        ):
            data["edges"].append(_norm_edge(
                critic_id, nopo_id, nopo_cond, _PATCH_ID,
            ))
            log.append(
                f"  [CRITIC_RETRY] Injected {critic_id}->{nopo_id} "
                f"(condition={nopo_cond!r})"
            )

    # critic → fallback_target: unconditional (success path)
    if not _has_edge(data, critic_id, fallback_target):
        data["edges"].append(_norm_edge(
            critic_id, fallback_target, None, _PATCH_ID,
        ))
        log.append(
            f"  [CRITIC_RETRY] Injected {critic_id}->{fallback_target} "
            f"(condition=None, unconditional fallback)"
        )

    return data, log


# ===========================================================================
# Pass 13 — Inject match_result == "UNKNOWN" guardrail edges
# ===========================================================================

def inject_match_result_unknown_guardrail(data: dict) -> tuple[dict, list[str]]:
    """For every gateway whose outgoing edges reference ``match_result``,
    ensure there is an edge handling ``match_result == "UNKNOWN"``.
    
    If missing, inject an edge to the ``task:MANUAL_REVIEW_UNMODELED_GATE``

    Args:
      data: dict:
      data: dict: 

    Returns:

    Raises:
      Contract: 
      Pre: Gateways with
      Post: Every
      Mutates: data

    """
    log: list[str] = []

    # Find the UNMODELED_GATE station by intent_key
    unmodeled_id: str | None = None
    for node in data.get("nodes", []):
        meta = node.get("meta") or {}
        ik = meta.get("intent_key") or meta.get("canonical_key", "")
        if ik == "task:MANUAL_REVIEW_UNMODELED_GATE":
            unmodeled_id = node["id"]
            break

    # Group outgoing edges by source
    edges_by_src: dict[str, list[dict]] = defaultdict(list)
    for edge in data.get("edges", []):
        edges_by_src[edge.get("frm", "")].append(edge)

    # Identify gateways with at least one match_result edge
    gateways_needing_unknown: list[str] = []
    for src_id, edges in edges_by_src.items():
        has_match_result_edge = False
        has_unknown_edge = False
        for e in edges:
            cond = e.get("condition") or ""
            if "match_result" in cond:
                has_match_result_edge = True
                if '"UNKNOWN"' in cond:
                    has_unknown_edge = True

        if has_match_result_edge and not has_unknown_edge:
            gateways_needing_unknown.append(src_id)

    if not gateways_needing_unknown:
        log.append("  [UNKNOWN] No match_result gateways need UNKNOWN edge")
        return data, log

    # Fail loudly if the station is missing
    if unmodeled_id is None:
        raise ValueError(
            "Cannot inject match_result == \"UNKNOWN\" guardrail: "
            "task:MANUAL_REVIEW_UNMODELED_GATE station not found in graph. "
            f"Gateways needing it: {gateways_needing_unknown}"
        )

    for gw_id in gateways_needing_unknown:
        condition = 'match_result == "UNKNOWN"'
        # Idempotency: skip if already present
        if any(
            e.get("frm") == gw_id and e.get("condition") == condition
            for e in data.get("edges", [])
        ):
            continue
        data["edges"].append(
            _norm_edge(gw_id, unmodeled_id, condition,
                       "normalize_match_result_unknown")
        )
        log.append(
            f"  [UNKNOWN] Injected edge {gw_id}->{unmodeled_id} "
            f'(condition=match_result == "UNKNOWN")'
        )

    return data, log


# ===========================================================================
# Pass 13 — Deduplicate edges
# ===========================================================================

def deduplicate_edges(data: dict) -> tuple[dict, list[str]]:
    """Remove edges that are identical after normalization:
    same (frm, to, normalized_condition).  First occurrence wins.
    
    Contract
    --------
    Pre:     Edges may have duplicates.
    Post:    No two edges share ``(frm, to, condition)``.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    seen: dict[tuple, int] = {}
    kept: list[dict] = []

    for idx, edge in enumerate(data.get("edges", [])):
        key = (
            edge.get("frm", ""),
            edge.get("to",  ""),
            edge.get("condition"),   # already normalized by pass 3
        )
        if key not in seen:
            seen[key] = idx
            kept.append(edge)
        else:
            log.append(
                f"  [DEDUP] Removed duplicate edge[{idx}] "
                f"({key[0]}->{key[1]}, cond={key[2]!r}) "
                f"(first at index {seen[key]})"
            )

    data["edges"] = kept
    return data, log


# ===========================================================================
# Pass 14 — Strict dedup (safety net after all injection passes)
# ===========================================================================

def deduplicate_edges_strict(data: dict) -> tuple[dict, list[str]]:
    """Final-pass safety net: remove edges with identical (frm, to, condition).
    
    Runs after all injection passes that could re-add edges.
    Uses the same key as the linter's E_EDGE_DUP check so the two stay
    in sync.  First occurrence wins.
    
    Contract
    --------
    Pre:     Safety-net after final passes.
    Post:    No two edges share ``(frm, to, condition)``.
    Mutates: ``data['edges']``.
    
    Args:
      data: dict:
    
    Returns:

    Args:
      data: dict: 

    Returns:

    
    """
    log: list[str] = []
    seen: dict[tuple, int] = {}
    kept: list[dict] = []

    for idx, edge in enumerate(data.get("edges", [])):
        key = (
            edge.get("frm", ""),
            edge.get("to",  ""),
            edge.get("condition"),
        )
        if key not in seen:
            seen[key] = idx
            kept.append(edge)
        else:
            log.append(
                f"  [DEDUP-STRICT] Removed duplicate edge[{idx}] "
                f"({key[0]}->{key[1]}, cond={key[2]!r}) "
                f"(first at index {seen[key]})"
            )

    data["edges"] = kept
    return data, log


# ===========================================================================
# Orchestrator
# ===========================================================================

def normalize_all(data: dict) -> tuple[dict, list[str]]:
    """Run all normalization passes in dependency order.
    
    Returns *(modified_data, changelog)*.
    All passes are idempotent; running twice yields the same graph.

    Args:
      data: dict:
      data: dict: 

    Returns:

    """
    all_log: list[str] = []

    passes: list[tuple[str, Callable]] = [
        ("fix_artifact_references",      fix_artifact_references),
        ("fix_canonical_key_duplicates", fix_canonical_key_duplicates),
        ("normalize_edge_conditions",    normalize_edge_conditions),
        ("inject_exception_nodes",       inject_exception_nodes),
        ("fix_match3way_gateway",        fix_match3way_gateway),
        ("fix_secondary_match_gateways", fix_secondary_match_gateways),
        ("fix_main_execution_path",      fix_main_execution_path),
        ("fix_haspo_gateway",            fix_haspo_gateway),
        ("fix_placeholder_gateways",     fix_placeholder_gateways),
        ("convert_unparseable_gateways_to_station", convert_unparseable_gateways_to_station),
        ("convert_whitelisted_fanout_to_sequential", convert_whitelisted_fanout_to_sequential),
        ("convert_fanout_gateways_to_ambiguous_station", convert_fanout_gateways_to_ambiguous_station),
        ("wire_bad_extraction_route",    wire_bad_extraction_route),
        ("wire_critic_retry_route",     wire_critic_retry_route),
        ("inject_match_result_unknown_guardrail", inject_match_result_unknown_guardrail),
        ("deduplicate_edges",            deduplicate_edges),
        ("deduplicate_edges_strict",     deduplicate_edges_strict),
    ]

    for name, fn in passes:
        data, log = fn(data)
        if log:
            all_log.append(f"[{name}]")
            all_log.extend(log)

    return data, all_log
