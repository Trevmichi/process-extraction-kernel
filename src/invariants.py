"""
invariants.py
Structural invariant checks for the AP process graph.

These are called by ``lint_process_graph()`` under section (E) and verify
patterns that must hold after normalisation.

Lint codes
----------
E_MATCH_SPLIT_MISSING_DECISION   — split task has no corresponding decision gateway
E_MATCH_SPLIT_BAD_TASK_TO_GATE   — task→decision wiring is wrong
E_MATCH_SPLIT_NON_EXHAUSTIVE     — decision gateway missing required branch conditions
E_MATCH_SPLIT_BYPASS_INBOUND     — decision gateway has inbound edge that bypasses the task
E_PLACEHOLDER_CONDITION          — edge condition is a miner placeholder that should
                                   have been resolved by normalisation
E_MATCH_RESULT_FOREIGN_WRITER    — node other than MATCH_3_WAY declares match_result
                                   in action.extra
E_MATCH_RESULT_WRONG_ROUTER      — a non-MATCH_DECISION node routes on match_result;
                                   match_result conditions must only appear on edges
                                   outgoing from a MATCH_DECISION gateway
E_MATCH_DECISION_TRUTH_TABLE     — a MATCH_DECISION gateway does not have exactly 3
                                   outgoing edges covering MATCH/NO_MATCH/UNKNOWN;
                                   also fires when an edge has a null/dangling target
                                   or carries a priority field
E_SYNTHETIC_INCOMPLETE           — a node with meta.synthetic=True is missing
                                   semantic_assumption or origin_pass; or a
                                   synthetic_edges entry is missing required fields
"""
from __future__ import annotations

from collections import defaultdict

from .conditions import normalize_condition
from .linter import LintError


# ---------------------------------------------------------------------------
# Known miner placeholders (action types that appear as conditions by mistake)
# ---------------------------------------------------------------------------

_PLACEHOLDER_CONDITIONS = frozenset({
    "IF_CONDITION",
    "SCHEDULE_PAYMENT",
    "EXECUTE_PAYMENT",
    "APPROVE",
})

# The canonical set of branch conditions for a MATCH_DECISION gateway
_MATCH_DECISION_CONDITIONS = frozenset({
    'match_result == "MATCH"',
    'match_result == "NO_MATCH"',
    'match_result == "UNKNOWN"',
})


# ===========================================================================
# E1 — Match split invariants
# ===========================================================================

def check_match_split_invariants(data: dict) -> list[LintError]:
    """Verify the task+decision split pattern for MATCH_3_WAY nodes.

    After normalisation, every node whose ``meta.intent_key`` or
    ``meta.canonical_key`` contains ``"gw:MATCH_3_WAY"`` (except n4, which
    is the primary match gateway handled by pass 5) must follow the split
    pattern: task (MATCH_3_WAY) → decision gateway (MATCH_DECISION).
    """
    errors: list[LintError] = []
    nodes_map: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])}
    edges = data.get("edges", [])

    # Build edge indices once to avoid O(n) list scans inside the candidate loop.
    edges_by_src: dict[str, list[dict]] = defaultdict(list)
    edges_by_tgt: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        src = e.get("frm")
        if src is not None:
            edges_by_src[src].append(e)
        tgt = e.get("to")
        if tgt is not None:
            edges_by_tgt[tgt].append(e)

    def _err(code: str, msg: str, **ctx: object) -> None:
        errors.append(LintError(code=code, severity="error", message=msg, context=ctx))

    # Find candidate nodes (gw:MATCH_3_WAY in meta, skip n4)
    candidates: list[dict] = []
    for node in data.get("nodes", []):
        if node["id"] == "n4":
            continue
        meta = node.get("meta") or {}
        ik = meta.get("intent_key") or ""
        ck = meta.get("canonical_key") or ""
        if "gw:MATCH_3_WAY" in ik or "gw:MATCH_3_WAY" in ck:
            candidates.append(node)

    for node in candidates:
        nid = node["id"]
        decision_id = f"{nid}_decision"

        # --- E_MATCH_SPLIT_MISSING_DECISION ---
        dec_node = nodes_map.get(decision_id)
        if dec_node is None:
            _err(
                "E_MATCH_SPLIT_MISSING_DECISION",
                f"Node {nid!r} has gw:MATCH_3_WAY meta but no "
                f"corresponding decision gateway {decision_id!r} exists",
                node_id=nid,
                expected_decision=decision_id,
            )
            continue
        if dec_node.get("kind") != "gateway":
            _err(
                "E_MATCH_SPLIT_MISSING_DECISION",
                f"Decision node {decision_id!r} exists but is "
                f"kind={dec_node.get('kind')!r}, expected 'gateway'",
                node_id=nid,
                decision_id=decision_id,
                actual_kind=dec_node.get("kind"),
            )
            continue
        dec_type = ((dec_node.get("decision") or {}).get("type") or "")
        if dec_type != "MATCH_DECISION":
            _err(
                "E_MATCH_SPLIT_MISSING_DECISION",
                f"Decision gateway {decision_id!r} has "
                f"decision.type={dec_type!r}, expected 'MATCH_DECISION'",
                node_id=nid,
                decision_id=decision_id,
                actual_decision_type=dec_type,
            )
            continue

        # --- E_MATCH_SPLIT_BAD_TASK_TO_GATE ---
        if node.get("kind") != "task":
            _err(
                "E_MATCH_SPLIT_BAD_TASK_TO_GATE",
                f"Node {nid!r} should be kind='task' after split, "
                f"got kind={node.get('kind')!r}",
                node_id=nid,
            )
        elif ((node.get("action") or {}).get("type") or "") != "MATCH_3_WAY":
            _err(
                "E_MATCH_SPLIT_BAD_TASK_TO_GATE",
                f"Node {nid!r} should have action.type='MATCH_3_WAY', "
                f"got {((node.get('action') or {}).get('type'))!r}",
                node_id=nid,
            )
        else:
            out = edges_by_src.get(nid, [])
            unconditional_to_dec = [
                e for e in out
                if e.get("to") == decision_id and e.get("condition") is None
            ]
            if len(out) != 1 or len(unconditional_to_dec) != 1:
                _err(
                    "E_MATCH_SPLIT_BAD_TASK_TO_GATE",
                    f"Task {nid!r} must have exactly 1 unconditional edge "
                    f"to {decision_id!r}; found {len(out)} outgoing edge(s), "
                    f"{len(unconditional_to_dec)} unconditional to decision",
                    node_id=nid,
                    decision_id=decision_id,
                    outgoing_count=len(out),
                )

        # --- E_MATCH_SPLIT_NON_EXHAUSTIVE ---
        dec_out = edges_by_src.get(decision_id, [])
        dec_conds = {e.get("condition") for e in dec_out}
        if dec_conds != _MATCH_DECISION_CONDITIONS:
            missing = _MATCH_DECISION_CONDITIONS - dec_conds
            extra = dec_conds - _MATCH_DECISION_CONDITIONS
            parts = []
            if missing:
                parts.append(f"missing={missing!r}")
            if extra:
                parts.append(f"extra={extra!r}")
            _err(
                "E_MATCH_SPLIT_NON_EXHAUSTIVE",
                f"Decision gateway {decision_id!r} must have exactly "
                f"3 canonical branch conditions; {'; '.join(parts)}",
                decision_id=decision_id,
                expected=sorted(_MATCH_DECISION_CONDITIONS),
                actual=sorted(str(c) for c in dec_conds),
            )

        # --- E_MATCH_SPLIT_BYPASS_INBOUND ---
        inbound = edges_by_tgt.get(decision_id, [])
        bypass = [e for e in inbound if e.get("frm") != nid]
        for e in bypass:
            _err(
                "E_MATCH_SPLIT_BYPASS_INBOUND",
                f"Decision gateway {decision_id!r} has inbound edge from "
                f"{e.get('frm')!r} (only {nid!r} should feed into it)",
                decision_id=decision_id,
                bypass_from=e.get("frm"),
                expected_from=nid,
            )

    return errors


# ===========================================================================
# E2 — No placeholder conditions remain
# ===========================================================================

def check_no_placeholder_conditions(data: dict) -> list[LintError]:
    """Verify no miner-placeholder conditions survived normalisation.

    Checks ALL edges (not just gateway edges): if a condition string is a
    known placeholder or normalises to ``None`` while being non-empty, it
    should have been resolved by the normalisation pipeline.
    """
    errors: list[LintError] = []

    for edge in data.get("edges", []):
        raw_cond = edge.get("condition")
        if raw_cond is None:
            continue

        raw_stripped = raw_cond.strip()
        if not raw_stripped:
            continue

        frm = edge.get("frm", "?")
        to = edge.get("to", "?")

        # (a) Known miner placeholder strings
        if raw_stripped.upper() in _PLACEHOLDER_CONDITIONS:
            errors.append(LintError(
                code="E_PLACEHOLDER_CONDITION",
                severity="error",
                message=(
                    f"Edge {frm!r} -> {to!r}: condition {raw_cond!r} is a "
                    f"miner placeholder that should have been resolved"
                ),
                context={"frm": frm, "to": to, "condition": raw_cond},
            ))
            continue

        # (b) Normalises to None (unresolved placeholder or unparseable)
        if normalize_condition(raw_cond) is None:
            errors.append(LintError(
                code="E_PLACEHOLDER_CONDITION",
                severity="error",
                message=(
                    f"Edge {frm!r} -> {to!r}: condition {raw_cond!r} "
                    f"normalises to None — placeholder not resolved"
                ),
                context={"frm": frm, "to": to, "condition": raw_cond},
            ))

    return errors


# ===========================================================================
# E3 — match_result ownership: only MATCH_3_WAY may write it
# ===========================================================================

def check_match_result_ownership(data: dict) -> list[LintError]:
    """Verify that no node other than MATCH_3_WAY declares ``match_result``
    in its ``action.extra`` metadata.

    At runtime, only the ``MATCH_3_WAY`` executor writes ``match_result``
    to state.  This static check catches rogue patches or normalisation
    passes that inject ``match_result`` references into other nodes'
    ``action.extra`` dicts.
    """
    errors: list[LintError] = []

    for node in data.get("nodes", []):
        action = node.get("action") or {}
        atype = action.get("type") or ""
        extra = action.get("extra") or {}

        if atype == "MATCH_3_WAY":
            continue

        if "match_result" in extra:
            errors.append(LintError(
                code="E_MATCH_RESULT_FOREIGN_WRITER",
                severity="error",
                message=(
                    f"Node {node['id']!r} (action.type={atype!r}) has "
                    f"'match_result' in action.extra — only MATCH_3_WAY "
                    f"nodes are allowed to produce match_result"
                ),
                context={
                    "node_id": node["id"],
                    "action_type": atype,
                },
            ))

    return errors


# ===========================================================================
# E4 — match_result routing: only MATCH_DECISION gateways may route on it
# ===========================================================================

def check_match_result_routing(data: dict) -> list[LintError]:
    """Verify that ``match_result`` conditions only appear on edges outgoing
    from a MATCH_DECISION gateway.

    Routing sanity check: MATCH_3_WAY (which sets ``match_result``) must
    execute before any node reads it via edge conditions.  Structurally,
    this means only the downstream MATCH_DECISION gateway should have
    ``match_result`` conditions on its outgoing edges.

    Catches regressions like pass 5 adding ``match_result`` edges to
    a non-gateway node (e.g. VALIDATE_FIELDS) that executes *before*
    MATCH_3_WAY has run.
    """
    errors: list[LintError] = []
    nodes_map: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])}

    # Identify MATCH_DECISION gateways
    match_decision_ids: set[str] = set()
    for node in data.get("nodes", []):
        if node.get("kind") == "gateway":
            dt = ((node.get("decision") or {}).get("type") or "")
            if dt == "MATCH_DECISION":
                match_decision_ids.add(node["id"])

    # Check every edge with a match_result condition
    for edge in data.get("edges", []):
        cond = edge.get("condition") or ""
        if "match_result" not in cond:
            continue
        frm = edge.get("frm", "?")
        if frm in match_decision_ids:
            continue
        # This edge routes on match_result but its source is NOT a MATCH_DECISION gateway
        src_node = nodes_map.get(frm)
        src_kind = (src_node or {}).get("kind", "?")
        src_action = ((src_node or {}).get("action") or {}).get("type", "?")
        errors.append(LintError(
            code="E_MATCH_RESULT_WRONG_ROUTER",
            severity="error",
            message=(
                f"Edge {frm!r} -> {edge.get('to', '?')!r}: routes on "
                f"match_result but source {frm!r} "
                f"(kind={src_kind!r}, action={src_action!r}) is not a "
                f"MATCH_DECISION gateway — match_result may not be set yet"
            ),
            context={
                "frm": frm,
                "to": edge.get("to", "?"),
                "condition": cond,
                "source_kind": src_kind,
                "source_action": src_action,
            },
        ))

    return errors


# ===========================================================================
# E5 — MATCH_DECISION truth table: exactly 3 exhaustive, exclusive branches
# ===========================================================================

def check_match_decision_truth_table(data: dict) -> list[LintError]:
    """Verify every ``MATCH_DECISION`` gateway has the canonical 3-branch
    truth table.

    Found by scanning ``decision.type == "MATCH_DECISION"`` directly
    (independent of meta tags or naming conventions).  Each must have
    exactly 3 outgoing edges whose conditions are:

        match_result == "MATCH"
        match_result == "NO_MATCH"
        match_result == "UNKNOWN"

    Additional checks:

    * Exactly one edge per canonical condition (no duplicates, no extras).
    * Every outgoing edge has a non-null ``to`` that references a node
      present in the graph.
    * No ``priority`` field on MATCH_DECISION outgoing edges (branches
      are condition-exclusive, so priority would introduce ambiguity).

    This is the explicit "decision truth table" check.  It overlaps with
    ``E_MATCH_SPLIT_NON_EXHAUSTIVE`` (which finds gateways via the
    ``gw:MATCH_3_WAY`` meta scan) but catches standalone MATCH_DECISION
    gateways that don't follow the split naming convention.
    """
    errors: list[LintError] = []
    edges = data.get("edges", [])
    nodes_map: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])}

    # Build an edges-by-source index once to avoid O(n) scans per gateway node.
    edges_by_src: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        src = e.get("frm")
        if src is not None:
            edges_by_src[src].append(e)

    for node in data.get("nodes", []):
        if node.get("kind") != "gateway":
            continue
        dt = ((node.get("decision") or {}).get("type") or "")
        if dt != "MATCH_DECISION":
            continue

        nid = node["id"]
        out_edges = edges_by_src.get(nid, [])
        out_conds = {e.get("condition") for e in out_edges}

        # --- Exhaustive condition check ---
        if out_conds != _MATCH_DECISION_CONDITIONS:
            missing = _MATCH_DECISION_CONDITIONS - out_conds
            extra = out_conds - _MATCH_DECISION_CONDITIONS
            parts = []
            if missing:
                parts.append(f"missing={sorted(missing)!r}")
            if extra:
                parts.append(f"extra={sorted(str(c) for c in extra)!r}")
            errors.append(LintError(
                code="E_MATCH_DECISION_TRUTH_TABLE",
                severity="error",
                message=(
                    f"MATCH_DECISION gateway {nid!r} must have exactly 3 "
                    f"outgoing edges (MATCH/NO_MATCH/UNKNOWN); "
                    f"{'; '.join(parts) or 'edge count mismatch'}"
                ),
                context={
                    "node_id": nid,
                    "expected": sorted(_MATCH_DECISION_CONDITIONS),
                    "actual": sorted(str(c) for c in out_conds),
                },
            ))

        # --- Exactly one edge per condition (mutual exclusivity) ---
        cond_list = [e.get("condition") for e in out_edges]
        seen: set[str | None] = set()
        for c in cond_list:
            if c in seen:
                errors.append(LintError(
                    code="E_MATCH_DECISION_TRUTH_TABLE",
                    severity="error",
                    message=(
                        f"MATCH_DECISION gateway {nid!r} has duplicate "
                        f"outgoing condition {c!r} — branches must be "
                        f"mutually exclusive"
                    ),
                    context={"node_id": nid, "duplicate_condition": c},
                ))
                break
            seen.add(c)

        # --- Edge count must be exactly 3 ---
        if len(out_edges) != 3:
            errors.append(LintError(
                code="E_MATCH_DECISION_TRUTH_TABLE",
                severity="error",
                message=(
                    f"MATCH_DECISION gateway {nid!r} must have exactly 3 "
                    f"outgoing edges, found {len(out_edges)}"
                ),
                context={
                    "node_id": nid,
                    "edge_count": len(out_edges),
                },
            ))

        # --- Each edge's `to` must be non-null and reference an existing node ---
        for e in out_edges:
            target = e.get("to")
            cond = e.get("condition", "?")
            if target is None:
                errors.append(LintError(
                    code="E_MATCH_DECISION_TRUTH_TABLE",
                    severity="error",
                    message=(
                        f"MATCH_DECISION gateway {nid!r}: outgoing edge "
                        f"with condition {cond!r} has null 'to' target"
                    ),
                    context={"node_id": nid, "condition": cond, "to": None},
                ))
            elif target not in nodes_map:
                errors.append(LintError(
                    code="E_MATCH_DECISION_TRUTH_TABLE",
                    severity="error",
                    message=(
                        f"MATCH_DECISION gateway {nid!r}: outgoing edge "
                        f"with condition {cond!r} targets {target!r} which "
                        f"does not exist in the graph"
                    ),
                    context={"node_id": nid, "condition": cond, "to": target},
                ))

        # --- No priority field on MATCH_DECISION edges (semantic purity) ---
        for e in out_edges:
            if "priority" in e:
                cond = e.get("condition", "?")
                errors.append(LintError(
                    code="E_MATCH_DECISION_TRUTH_TABLE",
                    severity="error",
                    message=(
                        f"MATCH_DECISION gateway {nid!r}: outgoing edge "
                        f"with condition {cond!r} has a 'priority' field "
                        f"(priority={e['priority']!r}) — MATCH_DECISION "
                        f"branches are condition-exclusive and must not use "
                        f"priority-based disambiguation"
                    ),
                    context={
                        "node_id": nid,
                        "condition": cond,
                        "priority": e["priority"],
                    },
                ))

        # --- Conditions must be exact canonical strings (no whitespace variants) ---
        for e in out_edges:
            raw_cond = e.get("condition")
            if raw_cond is None:
                continue
            normalized = normalize_condition(raw_cond)
            if normalized != raw_cond:
                errors.append(LintError(
                    code="E_MATCH_DECISION_TRUTH_TABLE",
                    severity="error",
                    message=(
                        f"MATCH_DECISION gateway {nid!r}: outgoing edge "
                        f"condition {raw_cond!r} is not in canonical form "
                        f"(expected {normalized!r}) — non-canonical conditions "
                        f"can bypass set-equality checks"
                    ),
                    context={
                        "node_id": nid,
                        "raw_condition": raw_cond,
                        "canonical_condition": normalized,
                    },
                ))

    return errors


# ===========================================================================
# E6 — Synthetic metadata completeness
# ===========================================================================

def check_synthetic_completeness(data: dict) -> list[LintError]:
    """Verify synthetic metadata completeness on nodes.

    Sub-check 1: Every node with ``meta.synthetic == True`` must have
    non-empty ``meta.semantic_assumption`` and ``meta.origin_pass``.

    Sub-check 2: Every node with ``meta.synthetic_edges`` (a list) must
    have each entry contain non-empty ``semantic_assumption`` and
    ``origin_pass``.
    """
    errors: list[LintError] = []

    for node in data.get("nodes", []):
        meta = node.get("meta") or {}
        nid = node.get("id", "?")

        # Sub-check 1: synthetic == True → require fields
        if meta.get("synthetic") is True:
            if not meta.get("semantic_assumption"):
                errors.append(LintError(
                    code="E_SYNTHETIC_INCOMPLETE",
                    severity="error",
                    message=(
                        f"Node {nid!r}: meta.synthetic is True but "
                        f"meta.semantic_assumption is missing or empty"
                    ),
                    context={"node_id": nid},
                ))
            if not meta.get("origin_pass"):
                errors.append(LintError(
                    code="E_SYNTHETIC_INCOMPLETE",
                    severity="error",
                    message=(
                        f"Node {nid!r}: meta.synthetic is True but "
                        f"meta.origin_pass is missing or empty"
                    ),
                    context={"node_id": nid},
                ))

        # Sub-check 2: synthetic_edges entries must be complete
        for idx, entry in enumerate(meta.get("synthetic_edges") or []):
            if not entry.get("semantic_assumption"):
                errors.append(LintError(
                    code="E_SYNTHETIC_INCOMPLETE",
                    severity="error",
                    message=(
                        f"Node {nid!r}: synthetic_edges[{idx}] is missing "
                        f"semantic_assumption"
                    ),
                    context={"node_id": nid, "entry_index": idx},
                ))
            if not entry.get("origin_pass"):
                errors.append(LintError(
                    code="E_SYNTHETIC_INCOMPLETE",
                    severity="error",
                    message=(
                        f"Node {nid!r}: synthetic_edges[{idx}] is missing "
                        f"origin_pass"
                    ),
                    context={"node_id": nid, "entry_index": idx},
                ))

    return errors
