"""
linter.py
Static validator for AP process graph JSON dictionaries.

Public API
----------
lint_process_graph(graph)  -> list[LintError]
assert_graph_valid(graph)  -> None   (raises ValueError on any error-severity issue)

Error codes
-----------
E_NODE_ID_DUP                  — duplicate node IDs
E_EDGE_REF                     — edge frm/to references a non-existent node
E_CANONICAL_KEY_MISSING        — node missing meta.canonical_key
E_CANONICAL_KEY_DUP            — canonical_key appears on multiple nodes
E_EDGE_DUP                     — duplicate (frm, to, condition) edge triple
E_ACTOR_MISSING                — action.actor_id not in actors list (or empty)
E_ARTIFACT_MISSING             — action.artifact_id not in artifacts list (or empty)
E_GATEWAY_TOO_FEW_EDGES        — gateway with fewer than 2 outgoing edges
E_GATEWAY_FANOUT_SAME_CONDITION— gateway with two or more edges sharing the same
                                  normalized condition (fan-out, not branch)
E_GATEWAY_NULL_CONDITION       — gateway edge has null condition (ambiguous routing)
E_CONDITION_PARSE              — edge condition cannot be normalised to valid DSL
E_MATCH_SPLIT_MISSING_DECISION — split task has no corresponding decision gateway
E_MATCH_SPLIT_BAD_TASK_TO_GATE — task→decision wiring is wrong
E_MATCH_SPLIT_NON_EXHAUSTIVE   — decision gateway missing required branch conditions
E_MATCH_SPLIT_BYPASS_INBOUND   — decision gateway has bypass inbound edge
E_PLACEHOLDER_CONDITION        — miner placeholder condition not resolved by normalisation
E_MATCH_RESULT_FOREIGN_WRITER  — non-MATCH_3_WAY node declares match_result in action.extra

Warning codes
-------------
W_GATEWAY_WIDE_FANOUT          — gateway with more than 3 outgoing edges
W_SEMANTIC_CONFLATION          — node kind/action/decision inconsistency
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .conditions import normalize_condition, parse_condition, ConditionParseError


# ---------------------------------------------------------------------------
# LintError dataclass
# ---------------------------------------------------------------------------

@dataclass
class LintError:
    code:     str
    severity: Literal["error", "warning"]
    message:  str
    context:  dict = field(default_factory=dict)

    def __str__(self) -> str:
        ctx = " | ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"[{self.severity.upper()}] {self.code}: {self.message}" + (
            f"  ({ctx})" if ctx else ""
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalized_or_none(raw: str | None) -> str | None:
    """Return the normalized form; ``None`` if raw is None or unrecognisable."""
    if raw is None:
        return None
    return normalize_condition(raw)


def _condition_parses(expr: str | None) -> bool:
    """True if *expr* is None or normalises + parses successfully."""
    if expr is None:
        return True
    norm = normalize_condition(expr)
    if norm is None:
        return False
    try:
        parse_condition(norm)
        return True
    except ConditionParseError:
        return False


# ---------------------------------------------------------------------------
# Main lint function
# ---------------------------------------------------------------------------

def lint_process_graph(graph: dict) -> list[LintError]:  # noqa: C901
    """
    Validate a parsed AP process graph dict.

    Returns a list of ``LintError`` instances (may be empty if the graph
    is valid).  Errors with severity ``"error"`` prevent safe compilation.
    Warnings indicate potential issues but do not block compilation.
    """
    errors: list[LintError] = []

    def err(code: str, msg: str, **ctx) -> None:
        errors.append(LintError(code=code, severity="error", message=msg, context=ctx))

    def warn(code: str, msg: str, **ctx) -> None:
        errors.append(LintError(code=code, severity="warning", message=msg, context=ctx))

    nodes: list[dict]    = graph.get("nodes", [])
    raw_edges: list[dict] = graph.get("edges", [])
    actors: list[dict]   = graph.get("actors", [])
    artifacts: list[dict] = graph.get("artifacts", [])

    # --- Index valid actor / artifact IDs ---
    actor_ids:    set[str] = {a["id"] for a in actors}
    artifact_ids: set[str] = {a["id"] for a in artifacts}

    # =========================================================================
    # (A) Node / edge referential integrity
    # =========================================================================

    # A1 — node IDs unique
    seen_node_ids: dict[str, int] = {}
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        if nid in seen_node_ids:
            err(
                "E_NODE_ID_DUP",
                f"Duplicate node ID {nid!r}",
                node_id=nid,
                first_index=seen_node_ids[nid],
                dup_index=i,
            )
        else:
            seen_node_ids[nid] = i

    node_ids: set[str] = set(seen_node_ids.keys())

    # A2 — edge frm/to must exist in nodes
    for idx, edge in enumerate(raw_edges):
        frm = edge.get("frm", "")
        to  = edge.get("to",  "")
        if frm not in node_ids:
            err(
                "E_EDGE_REF",
                f"Edge[{idx}] frm={frm!r} references a non-existent node",
                edge_idx=idx,
                node_id=frm,
            )
        if to not in node_ids:
            err(
                "E_EDGE_REF",
                f"Edge[{idx}] to={to!r} references a non-existent node",
                edge_idx=idx,
                node_id=to,
            )

    # A3 — canonical_key present and unique
    seen_canonical: dict[str, str] = {}  # canonical_key -> first node_id
    for node in nodes:
        nid  = node.get("id", "")
        meta = node.get("meta") or {}
        ckey = meta.get("canonical_key")
        if not ckey:
            err(
                "E_CANONICAL_KEY_MISSING",
                f"Node {nid!r} is missing meta.canonical_key",
                node_id=nid,
            )
        else:
            if ckey in seen_canonical:
                err(
                    "E_CANONICAL_KEY_DUP",
                    f"canonical_key {ckey!r} is shared by nodes "
                    f"{seen_canonical[ckey]!r} and {nid!r}",
                    canonical_key=ckey,
                    first_node_id=seen_canonical[ckey],
                    dup_node_id=nid,
                )
            else:
                seen_canonical[ckey] = nid

    # A4 — no duplicate (frm, to, condition) edges
    seen_triples: dict[tuple[str, str, str | None], int] = {}
    for idx, edge in enumerate(raw_edges):
        triple = (edge.get("frm", ""), edge.get("to", ""), edge.get("condition"))
        if triple in seen_triples:
            err(
                "E_EDGE_DUP",
                f"Duplicate edge ({triple[0]!r} -> {triple[1]!r}, "
                f"cond={triple[2]!r}) at index {idx} "
                f"(first seen at index {seen_triples[triple]})",
                edge_idx=idx,
                frm=triple[0],
                to=triple[1],
                condition=triple[2],
                first_edge_idx=seen_triples[triple],
            )
        else:
            seen_triples[triple] = idx

    # =========================================================================
    # (B) Actor / artifact integrity
    # =========================================================================

    for node in nodes:
        nid    = node.get("id", "")
        action = node.get("action") or {}
        if not action:
            continue

        actor_id    = action.get("actor_id",    "")
        artifact_id = action.get("artifact_id", "")

        if not actor_id:
            err(
                "E_ACTOR_MISSING",
                f"Node {nid!r} action.actor_id is empty",
                node_id=nid,
            )
        elif actor_id not in actor_ids:
            err(
                "E_ACTOR_MISSING",
                f"Node {nid!r} action.actor_id={actor_id!r} not in actors list",
                node_id=nid,
                actor_id=actor_id,
            )

        if not artifact_id:
            err(
                "E_ARTIFACT_MISSING",
                f"Node {nid!r} action.artifact_id is empty",
                node_id=nid,
            )
        elif artifact_id not in artifact_ids:
            err(
                "E_ARTIFACT_MISSING",
                f"Node {nid!r} action.artifact_id={artifact_id!r} not found in "
                f"artifacts list",
                node_id=nid,
                artifact_id=artifact_id,
            )

    # =========================================================================
    # (C) Gateway semantics
    # =========================================================================

    # Build outgoing edge index
    from collections import defaultdict
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in raw_edges:
        frm = edge.get("frm", "")
        if frm in node_ids:
            outgoing[frm].append(edge)

    for node in nodes:
        nid  = node.get("id", "")
        kind = node.get("kind", "")

        if kind != "gateway":
            continue

        out_edges = outgoing.get(nid, [])

        # C1 — must have ≥2 outgoing edges
        if len(out_edges) < 2:
            err(
                "E_GATEWAY_TOO_FEW_EDGES",
                f"Gateway {nid!r} has {len(out_edges)} outgoing edge(s); "
                f"at least 2 are required for a branch",
                node_id=nid,
                outgoing_count=len(out_edges),
            )
            # No point checking further for this gateway
            continue

        # C2 — warn if more than 3 outgoing edges
        if len(out_edges) > 3:
            warn(
                "W_GATEWAY_WIDE_FANOUT",
                f"Gateway {nid!r} has {len(out_edges)} outgoing edges "
                f"(>3 often indicates fan-out misuse)",
                node_id=nid,
                outgoing_count=len(out_edges),
            )

        # C3 — no null conditions on gateway edges
        # C4 — conditions must parse under DSL
        # C5 — no two edges may share the same normalized condition
        normalized_conditions: list[str | None] = []

        for idx, edge in enumerate(out_edges):
            raw_cond = edge.get("condition")
            to       = edge.get("to", "")

            if raw_cond is None:
                err(
                    "E_GATEWAY_NULL_CONDITION",
                    f"Gateway {nid!r} -> {to!r}: edge has null condition; "
                    f"gateway edges must have explicit conditions",
                    node_id=nid,
                    to=to,
                    edge_idx=idx,
                )
                normalized_conditions.append(None)
                continue

            norm = normalize_condition(raw_cond)
            if norm is None:
                err(
                    "E_CONDITION_PARSE",
                    f"Gateway {nid!r} -> {to!r}: condition {raw_cond!r} cannot "
                    f"be normalised to a valid DSL expression",
                    node_id=nid,
                    to=to,
                    condition=raw_cond,
                )
                normalized_conditions.append(None)
                continue

            # Validate that the normalized form parses
            try:
                parse_condition(norm)
            except ConditionParseError as exc:
                err(
                    "E_CONDITION_PARSE",
                    f"Gateway {nid!r} -> {to!r}: normalized condition "
                    f"{norm!r} failed DSL parse: {exc}",
                    node_id=nid,
                    to=to,
                    condition=raw_cond,
                    normalized=norm,
                )
                normalized_conditions.append(None)
                continue

            normalized_conditions.append(norm)

        # C5 — check for duplicate normalized conditions
        seen_norm: dict[str, str] = {}  # norm -> first target node_id
        for edge, norm in zip(out_edges, normalized_conditions):
            if norm is None:
                continue
            to = edge.get("to", "")
            if norm in seen_norm:
                err(
                    "E_GATEWAY_FANOUT_SAME_CONDITION",
                    f"Gateway {nid!r}: edges to {seen_norm[norm]!r} and "
                    f"{to!r} share the same normalized condition {norm!r} — "
                    f"this is fan-out (parallel dispatch), not a branch",
                    node_id=nid,
                    condition=norm,
                    first_target=seen_norm[norm],
                    dup_target=to,
                )
            else:
                seen_norm[norm] = to

    # =========================================================================
    # (D) Decision / task semantic consistency (warnings)
    # =========================================================================

    for node in nodes:
        nid      = node.get("id", "")
        kind     = node.get("kind", "")
        action   = node.get("action")
        decision = node.get("decision")

        if kind == "gateway":
            if decision is None or not (decision or {}).get("type"):
                warn(
                    "W_SEMANTIC_CONFLATION",
                    f"Gateway node {nid!r} has no decision field",
                    node_id=nid,
                )
            if action is not None:
                warn(
                    "W_SEMANTIC_CONFLATION",
                    f"Gateway node {nid!r} has a non-null action field "
                    f"(gateways should only have decision)",
                    node_id=nid,
                )

        elif kind == "task":
            if action is None:
                warn(
                    "W_SEMANTIC_CONFLATION",
                    f"Task node {nid!r} has no action field",
                    node_id=nid,
                )
            if decision is not None:
                warn(
                    "W_SEMANTIC_CONFLATION",
                    f"Task node {nid!r} has a non-null decision field "
                    f"(tasks should only have action)",
                    node_id=nid,
                )
            # Check if action.type == decision.type (semantics conflated)
            if action and decision:
                atype = (action  or {}).get("type", "")
                dtype = (decision or {}).get("type", "")
                if atype and dtype and atype == dtype:
                    warn(
                        "W_SEMANTIC_CONFLATION",
                        f"Node {nid!r} action.type == decision.type == {atype!r}",
                        node_id=nid,
                        type=atype,
                    )

    # =========================================================================
    # (E) Structural patterns (invariants)
    # =========================================================================

    from .invariants import (
        check_match_decision_truth_table,
        check_match_result_ownership,
        check_match_result_routing,
        check_match_split_invariants,
        check_no_placeholder_conditions,
        check_synthetic_completeness,
    )

    errors.extend(check_match_split_invariants(graph))
    errors.extend(check_no_placeholder_conditions(graph))
    errors.extend(check_match_result_ownership(graph))
    errors.extend(check_match_result_routing(graph))
    errors.extend(check_match_decision_truth_table(graph))
    errors.extend(check_synthetic_completeness(graph))

    return errors


# ---------------------------------------------------------------------------
# Hard assertion (used by compiler)
# ---------------------------------------------------------------------------

def assert_graph_valid(graph: dict) -> None:
    """
    Lint *graph* and raise ``ValueError`` if any error-severity issues exist.

    The exception message contains a human-readable multi-line report of
    all errors (warnings are included for context but do not trigger the
    raise).

    Safe to call before graph compilation; blocks compilation on invalid
    input (fail-closed behaviour).
    """
    lint_results = lint_process_graph(graph)

    error_items   = [e for e in lint_results if e.severity == "error"]
    warning_items = [e for e in lint_results if e.severity == "warning"]

    if not error_items:
        return  # graph is valid (warnings are OK)

    lines = [
        "Graph validation failed — cannot compile.",
        f"  {len(error_items)} error(s), {len(warning_items)} warning(s).",
        "",
        "ERRORS:",
    ]
    for e in error_items:
        lines.append(f"  • {e}")

    if warning_items:
        lines.append("")
        lines.append("WARNINGS (non-blocking):")
        for w in warning_items:
            lines.append(f"  ⚠ {w}")

    raise ValueError("\n".join(lines))
