from __future__ import annotations
from typing import List, Dict, Set
from .models import ProcessDoc, Node

def validate(process: ProcessDoc) -> List[str]:
    """

    Args:
      process: ProcessDoc: 

    Returns:

    """
    errors: List[str] = []
    nodes_by_id: Dict[str, Node] = {n.id: n for n in process.nodes}

    starts = [n for n in process.nodes if n.kind == "event"]
    ends = [n for n in process.nodes if n.kind == "end"]
    if len(starts) != 1:
        errors.append(f"Expected exactly 1 start event node; found {len(starts)}")
    if len(ends) < 1:
        errors.append("Expected at least 1 end node; found 0")

    for e in process.edges:
        if e.frm not in nodes_by_id:
            errors.append(f"Edge from unknown node: {e.frm}")
        if e.to not in nodes_by_id:
            errors.append(f"Edge to unknown node: {e.to}")

    if starts:
        start_id = starts[0].id
        adj: Dict[str, List[str]] = {}
        for e in process.edges:
            adj.setdefault(e.frm, []).append(e.to)

        seen: Set[str] = set()
        stack = [start_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in adj.get(cur, []):
                stack.append(nxt)

        unreachable = [n.id for n in process.nodes if n.id not in seen]
        if unreachable:
            errors.append(f"Unreachable nodes: {unreachable}")

    for n in process.nodes:
        if not n.evidence and n.kind in ("task", "gateway", "event", "end"):
            errors.append(f"Node {n.id} has no evidence (must add or mark as assumption)")

        if n.kind == "task":
            if n.action is None:
                errors.append(f"Task node {n.id} missing action")
            else:
                if not n.action.type or not n.action.actor_id or not n.action.artifact_id:
                    errors.append(f"Task node {n.id} action missing required fields")
        if n.kind == "gateway":
            if n.decision is None or not n.decision.type:
                errors.append(f"Gateway node {n.id} missing decision")

    return errors
