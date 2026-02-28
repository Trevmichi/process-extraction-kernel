from __future__ import annotations
from typing import Dict, List
from .models import ProcessDoc, Node

def _node_label(n: Node) -> str:
    base = n.name.strip() if n.name else n.id
    if n.kind == "task" and n.action:
        base = f"{base}\\n[{n.action.type}]"
    if n.kind == "gateway" and n.decision:
        base = f"{base}\\n<{n.decision.type}>"
    return base.replace('"', "'")

def _node_style(n: Node) -> str:
    if n.kind == "event":
        return f"  style {n.id} fill:#9f9,stroke:#333,stroke-width:2px"
    if n.kind == "end":
        return f"  style {n.id} fill:#f99,stroke:#333,stroke-width:2px"
    if n.kind == "gateway":
        return f"  style {n.id} fill:#fdb,stroke:#333,stroke-width:1px"
    # task (and any other kind)
    return f"  style {n.id} fill:#bbf,stroke:#333,stroke-width:1px"

def to_mermaid(process: ProcessDoc) -> str:
    nodes_by_id: Dict[str, Node] = {n.id: n for n in process.nodes}

    lines: List[str] = []
    lines.append("flowchart LR")

    # Node declarations with shapes
    for n in process.nodes:
        label = _node_label(n)
        if n.kind == "event":
            lines.append(f'  {n.id}(["{label}"])')
        elif n.kind == "end":
            lines.append(f'  {n.id}([["{label}"]])')
        elif n.kind == "gateway":
            lines.append(f'  {n.id}{{"{label}"}}')
        else:
            lines.append(f'  {n.id}["{label}"]')

    # Edges
    for e in process.edges:
        cond = (e.condition or "").strip()
        if cond:
            lines.append(f"  {e.frm} -->|{cond}| {e.to}")
        else:
            lines.append(f"  {e.frm} --> {e.to}")

    # Optional: legend-ish notes for unknowns count
    unk_count = len(process.unknowns or [])
    if unk_count:
        lines.append(f'  U_NOTE["Unknowns: {unk_count} (see JSON unknowns list)"]')
        # attach note to start node if possible
        starts = [n for n in process.nodes if n.kind == "event"]
        if starts:
            lines.append(f"  {starts[0].id} -.-> U_NOTE")

    # Individual style statements (maximum IDE compatibility)
    for n in process.nodes:
        lines.append(_node_style(n))

    return "\n".join(lines) + "\n"
