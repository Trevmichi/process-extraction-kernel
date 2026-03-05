from __future__ import annotations
from typing import Optional
from .models import ProcessDoc, Node, Edge, Action

def _ck(n: Node) -> str:
    """

    Args:
      n: Node:
      n: Node: 

    Returns:

    """
    return (n.meta or {}).get("canonical_key", "")

def _find_by_ck(proc: ProcessDoc, ck: str) -> Optional[Node]:
    """Find node by meta.canonical_key, but fall back to (kind + action.type) when meta is missing/inconsistent.
    ck examples: "task:SCHEDULE_PAYMENT", "gw:MATCH_3_WAY", "event:start", "end:end"

    Args:
      proc: ProcessDoc:
      ck: str:
      proc: ProcessDoc: 
      ck: str: 

    Returns:

    """
    # 1) canonical_key match
    for n in proc.nodes:
        if (n.meta or {}).get("canonical_key", "") == ck:
            return n

    # 2) fallback: kind + action.type
    if ":" in ck:
        kind_prefix, type_name = ck.split(":", 1)
        kind_map = {"task": "task", "gw": "gateway", "event": "event", "end": "end"}
        want_kind = kind_map.get(kind_prefix, None)

        for n in proc.nodes:
            if want_kind and n.kind != want_kind:
                continue

            # node.action may be None for some nodes
            a = getattr(n, "action", None)
            a_type = getattr(a, "type", None)

            if a_type == type_name:
                return n

    return None


def _find_by_ck_or_type(proc: ProcessDoc, ck: str, kind: str, type_name: str) -> Optional[Node]:
    """

    Args:
      proc: ProcessDoc:
      ck: str:
      kind: str:
      type_name: str:
      proc: ProcessDoc: 
      ck: str: 
      kind: str: 
      type_name: str: 

    Returns:

    """
    # Try canonical_key first
    n = _find_by_ck(proc, ck)
    if n is not None:
        return n
    # Fallback: kind + action.type
    for node in proc.nodes:
        if node.kind != kind:
            continue
        a = getattr(node, "action", None)
        if getattr(a, "type", None) == type_name:
            return node
    return None

def _next_id(proc: ProcessDoc) -> str:
    """

    Args:
      proc: ProcessDoc:
      proc: ProcessDoc: 

    Returns:

    """
    used = set(n.id for n in proc.nodes)
    i = 1
    while True:
        cand = f"n{i}"
        if cand not in used:
            return cand
        i += 1

def canonicalize_manual_to_explicit(proc: ProcessDoc) -> None:
    """Manual -> Explicit canonicalization:
    - event -> event:start
    - ensure RECEIVE_MESSAGE exists after start
    - end -> end:end
    - expand SCHEDULE_PAYMENT -> end into SCHEDULE_PAYMENT -> EXECUTE_PAYMENT -> end

    Args:
      proc: ProcessDoc:
      proc: ProcessDoc: 

    Returns:

    """

    # Normalize start event -> event:start
    start = next((n for n in proc.nodes if n.kind == "event"), None)
    if start:
        start.name = "Start"
        start.meta = start.meta or {}
        start.meta["canonical_key"] = "event:start"

    # Ensure RECEIVE_MESSAGE exists right after start
    recv = _find_by_ck(proc, "task:RECEIVE_MESSAGE")
    if start and recv is None:
        recv_id = _next_id(proc)
        recv = Node(
            id=recv_id,
            kind="task",
            name="Receive invoice/message",
            action=Action(type="RECEIVE_MESSAGE", actor_id="sys_erp", artifact_id="art_invoice"),
            evidence=getattr(start, "evidence", None) or [],
            meta={"canonical_key": "task:RECEIVE_MESSAGE"},
        )
        proc.nodes.append(recv)

        # Reroute outgoing edges from start to come from recv
        old_start_id = start.id
        outgoing = [e for e in proc.edges if e.frm == old_start_id]
        for e in outgoing:
            e.frm = recv_id

        # Add start -> recv edge
        proc.edges.append(Edge(frm=old_start_id, to=recv_id))

    # Normalize end -> end:end (and keep the same node id)
    end = next((n for n in proc.nodes if n.kind == "end"), None)
    if end:
        end.name = "End"
        end.meta = end.meta or {}
        end.meta["canonical_key"] = "end:end"

    # Expand payment tail: ensure SCHEDULE_PAYMENT -> EXECUTE_PAYMENT -> END
    sched = _find_by_ck_or_type(proc, "task:SCHEDULE_PAYMENT", "task", "SCHEDULE_PAYMENT")
    end_nodes = [n for n in proc.nodes if n.kind == "end"]
    end = end_nodes[0] if end_nodes else None
    execp = _find_by_ck_or_type(proc, "task:EXECUTE_PAYMENT", "task", "EXECUTE_PAYMENT")

    if sched and end:
        # Create EXECUTE_PAYMENT node if missing
        if execp is None:
            exec_id = _next_id(proc)
            execp = Node(
                id=exec_id,
                kind="task",
                name="Execute payment",
                action=Action(type="EXECUTE_PAYMENT", actor_id="sys_erp", artifact_id="art_payment"),
                evidence=getattr(sched, "evidence", None) or [],
                meta={"canonical_key": "task:EXECUTE_PAYMENT"},
            )
            proc.nodes.append(execp)

        # Ensure edges exist: sched -> exec and exec -> end
        if not any(e.frm == sched.id and e.to == execp.id for e in proc.edges):
            proc.edges.append(Edge(frm=sched.id, to=execp.id))
        if not any(e.frm == execp.id and e.to == end.id for e in proc.edges):
            proc.edges.append(Edge(frm=execp.id, to=end.id))

        # If sched was directly connected to an end, remove that direct edge (cleaner canonical form)
        end_ids = set(n.id for n in proc.nodes if n.kind == "end")
        proc.edges = [e for e in proc.edges if not (e.frm == sched.id and e.to in end_ids)]





