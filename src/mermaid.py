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

def to_mermaid(process: ProcessDoc) -> str:
    nodes_by_id: Dict[str, Node] = {n.id: n for n in process.nodes}

    lines: List[str] = []
    lines.append("flowchart LR")

    # Node declarations with shapes and class annotations
    for n in process.nodes:
        label = _node_label(n)
        if n.kind == "event":
            lines.append(f'  {n.id}(["{label}"]):::start_node')
        elif n.kind == "end":
            lines.append(f'  {n.id}([["{label}"]]):::end_node')
        elif n.kind == "gateway":
            lines.append(f'  {n.id}{{"{label}"}}:::decision_node')
        else:
            lines.append(f'  {n.id}["{label}"]:::action_node')

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

    # Styling
    lines.append("  classDef start_node fill:#9f9,stroke:#333,stroke-width:2px;")
    lines.append("  classDef end_node fill:#f99,stroke:#333,stroke-width:2px;")
    lines.append("  classDef action_node fill:#bbf,stroke:#333,stroke-width:1px;")
    lines.append("  classDef decision_node fill:#fdb,stroke:#333,stroke-width:1px;")

    return "\n".join(lines) + "\n"
