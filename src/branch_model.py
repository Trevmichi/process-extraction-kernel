from __future__ import annotations
import re
from typing import Dict, List, Optional
from .models import ProcessDoc, Edge, Node, Action

ADD_IMPLIED_WITHIN_TOLERANCE = False  # set True to auto-add within_tolerance edge

def _ck(n: Node) -> str:
    return (n.meta or {}).get("canonical_key", "")

def _find_node_by_ck(proc: ProcessDoc, ck: str) -> Optional[Node]:
    for n in proc.nodes:
        if _ck(n) == ck:
            return n
    return None

def _has_edge(proc: ProcessDoc, frm: str, to: str, cond: Optional[str]) -> bool:
    for e in proc.edges:
        if e.frm == frm and e.to == to and (e.condition or None) == (cond or None):
            return True
    return False

def _has_labeled_out(proc: ProcessDoc, gw_id: str) -> bool:
    return any(e.frm == gw_id and (e.condition or "").strip() != "" for e in proc.edges)

def _prune_branch_unknown(proc: ProcessDoc, snippet_contains: str) -> None:
    # Remove only the generic "Decision detected..." unknown for a given sentence snippet
    proc.unknowns = [
        u for u in (proc.unknowns or [])
        if not (u.get("type") == "missing_path" and snippet_contains in (u.get("question") or ""))
    ]

def _next_id(proc: ProcessDoc) -> str:
    used = {n.id for n in proc.nodes}
    i = 1
    while f"n{i}" in used:
        i += 1
    return f"n{i}"

def apply_branch_model(proc: ProcessDoc) -> List[Dict]:
    """
    Adds simple branch edges for known gateway types.
    Returns list of edits made (for trace/debug).
    """
    edits: List[Dict] = []

    # 0) Inject implicit RECEIVE_MESSAGE if HAS_PO gateway exists but no RECEIVE_MESSAGE task
    _gw_has_po = _find_node_by_ck(proc, "gw:HAS_PO")
    if _gw_has_po and _find_node_by_ck(proc, "task:RECEIVE_MESSAGE") is None:
        _start = next(
            (n for n in proc.nodes if n.kind == "event" and (
                _ck(n) == "event:start" or (n.name or "").strip().lower() == "start"
            )),
            None,
        )
        if _start:
            _start_out = next((e for e in proc.edges if e.frm == _start.id), None)
            _new_id = _next_id(proc)
            _recv_node = Node(
                id=_new_id,
                kind="task",
                name="Receive invoice",
                action=Action(type="RECEIVE_MESSAGE", actor_id="", artifact_id=""),
                meta={"canonical_key": "task:RECEIVE_MESSAGE"},
            )
            proc.nodes.append(_recv_node)
            proc.edges.append(Edge(frm=_start.id, to=_new_id))
            if _start_out is not None:
                _start_out.frm = _new_id
            edits.append({"type": "inject_node", "id": _new_id, "canonical_key": "task:RECEIVE_MESSAGE"})

    gw_thr = _find_node_by_ck(proc, "gw:THRESHOLD_AMOUNT")
    gw_match = _find_node_by_ck(proc, "gw:MATCH_3_WAY")
    approve = _find_node_by_ck(proc, "task:APPROVE")

    # 1) THRESHOLD_AMOUNT: add two labeled edges to APPROVE (if present)
    if gw_thr and approve:
        expr = (gw_thr.decision.expression if gw_thr.decision else "") or ""
        m = re.search(r">\s*([0-9]+)", expr)
        thresh = m.group(1) if m else "THRESH"

        hi = f"amount>{thresh}"
        lo = f"amount<={thresh}"

        if not _has_edge(proc, gw_thr.id, approve.id, hi):
            proc.edges.append(Edge(frm=gw_thr.id, to=approve.id, condition=hi))
            edits.append({"type": "add_edge", "from": "gw:THRESHOLD_AMOUNT", "to": "task:APPROVE", "condition": hi})

        if not _has_edge(proc, gw_thr.id, approve.id, lo):
            proc.edges.append(Edge(frm=gw_thr.id, to=approve.id, condition=lo))
            edits.append({"type": "add_edge", "from": "gw:THRESHOLD_AMOUNT", "to": "task:APPROVE", "condition": lo})

        # doc_001 cleanup: wire APPROVE -> SCHEDULE_PAYMENT directly
        sched = _find_node_by_ck(proc, "task:SCHEDULE_PAYMENT")
        if sched:
            # Remove sequential artifact: APPROVE -> THRESHOLD_AMOUNT
            before = len(proc.edges)
            proc.edges = [e for e in proc.edges if not (e.frm == approve.id and e.to == gw_thr.id)]
            if len(proc.edges) < before:
                edits.append({"type": "remove_edge", "from": "task:APPROVE", "to": "gw:THRESHOLD_AMOUNT"})

            # Remove any edge: THRESHOLD_AMOUNT -> SCHEDULE_PAYMENT
            before = len(proc.edges)
            proc.edges = [e for e in proc.edges if not (e.frm == gw_thr.id and e.to == sched.id)]
            if len(proc.edges) < before:
                edits.append({"type": "remove_edge", "from": "gw:THRESHOLD_AMOUNT", "to": "task:SCHEDULE_PAYMENT"})

            # Ensure APPROVE -> SCHEDULE_PAYMENT (unlabeled)
            if not _has_edge(proc, approve.id, sched.id, None):
                proc.edges.append(Edge(frm=approve.id, to=sched.id, condition=None))
                edits.append({"type": "add_edge", "from": "task:APPROVE", "to": "task:SCHEDULE_PAYMENT", "condition": None})

    # 2) MATCH_3_WAY: add "match" edge to THRESHOLD gateway if present, else APPROVE
    if gw_match:
        target = gw_thr or approve
        if target:
            has_match = any(
                e.frm == gw_match.id and (e.condition or "").strip().lower() == "match"
                for e in proc.edges
            )
            if not has_match:
                proc.edges.append(Edge(frm=gw_match.id, to=target.id, condition="match"))
                edits.append({"type": "add_edge", "from": "gw:MATCH_3_WAY", "to": _ck(target) or target.id, "condition": "match"})

        # Ensure the missing no_match path is represented as an unknown
        q = "If 3-way match fails (no_match), what is the process (hold, vendor contact, reject, override)?"
        existing = set(u.get("question", "") for u in (proc.unknowns or []))
        if q not in existing:
            proc.unknowns.append({"id": f"auto_u{len(proc.unknowns)+1}", "type": "missing_path", "question": q, "priority": "high"})
            edits.append({"type": "add_unknown", "question": q})

        # Domain prior: 3-way match tolerance is usually a required rule (even if not stated)
        q2 = "What is the match tolerance for price/quantity variances in matching (and who sets it)?"
        existing2 = set(u.get("question", "") for u in (proc.unknowns or []))
        if q2 not in existing2:
            proc.unknowns.append({"id": f"auto_u{len(proc.unknowns)+1}", "type": "missing_rule", "question": q2, "priority": "medium"})
            edits.append({"type": "add_unknown", "question": q2})

    # 2.5) VARIANCE_ABOVE_TOLERANCE: ensure both above_tolerance and within_tolerance are represented
    gw_var = _find_node_by_ck(proc, "gw:VARIANCE_ABOVE_TOLERANCE")
    match_task = _find_node_by_ck(proc, "task:MATCH_3_WAY")
    end_nodes = [n for n in proc.nodes if n.kind == "end"]
    end = end_nodes[0] if end_nodes else None

    if gw_var and ADD_IMPLIED_WITHIN_TOLERANCE:
        # above_tolerance typically exists already; ensure within_tolerance exists
        # Prefer sending within_tolerance to MATCH_3_WAY if present, else End
        target = match_task or end
        if target:
            if not _has_edge(proc, gw_var.id, target.id, "within_tolerance"):
                proc.edges.append(Edge(frm=gw_var.id, to=target.id, condition="within_tolerance"))
                edits.append({"type": "add_edge", "from": "gw:VARIANCE_ABOVE_TOLERANCE", "to": _ck(target) or target.id, "condition": "within_tolerance"})

    # 3) Remove redundant unlabeled edges when labeled edge exists for same frm->to
    labeled_pairs = {(e.frm, e.to) for e in proc.edges if (e.condition or "").strip() != ""}
    proc.edges = [
        e for e in proc.edges
        if not ((e.frm, e.to) in labeled_pairs and ((e.condition or "").strip() == ""))
    ]

    # 4) Prune noisy "Decision detected..." unknowns if we actually created labeled branch edges
    # (These snippet strings match the questions produced by heuristic.py)
    if gw_match and _has_labeled_out(proc, gw_match.id):
        _prune_branch_unknown(proc, "If the invoice matches the PO and goods receipt")
    if gw_thr and _has_labeled_out(proc, gw_thr.id):
        _prune_branch_unknown(proc, "Invoices over $5,000 require director approval")
    if gw_var and _has_labeled_out(proc, gw_var.id):
        _prune_branch_unknown(proc, "If there is a quantity mismatch or price variance above the tolerance")
    gw_has_po_node = _find_node_by_ck(proc, "gw:HAS_PO")
    gw_aor = _find_node_by_ck(proc, "gw:APPROVE_OR_REJECT")
    if gw_has_po_node and _has_labeled_out(proc, gw_has_po_node.id):
        _prune_branch_unknown(proc, "If an invoice does not have a PO number")
    if gw_aor and _has_labeled_out(proc, gw_aor.id):
        _prune_branch_unknown(proc, "If the manager rejects the expense")

    return edits

