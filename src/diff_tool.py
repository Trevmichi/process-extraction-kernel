from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

def _load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _norm_key(k: str) -> str:
    k = (k or "").strip()
    if not k:
        return ""
    # unify separators
    k = k.replace("::", ":")
    # standardize prefixes
    if k.lower().startswith("task:"):
        return "task:" + k.split(":", 1)[1].upper()
    if k.lower().startswith("gw:") or k.lower().startswith("gateway:"):
        tail = k.split(":", 1)[1]
        return "gw:" + tail.upper()
    if k.lower().startswith("event:"):
        return "event:" + k.split(":", 1)[1].lower()
    if k.lower().startswith("end:"):
        return "end:" + k.split(":", 1)[1].lower()
    return k

def _node_key(n: Dict[str, Any]) -> str:
    meta = n.get("meta") or {}
    ck = _norm_key(meta.get("canonical_key") or "")
    if ck:
        return ck

    kind = (n.get("kind", "") or "").lower()
    action_type = (n.get("action") or {}).get("type")
    decision_type = (n.get("decision") or {}).get("type")
    name = (n.get("name") or "").strip().lower()

    if kind == "task" and action_type:
        return _norm_key(f"task:{action_type}")
    if kind == "gateway" and decision_type:
        return _norm_key(f"gw:{decision_type}")
    if kind == "event":
        return _norm_key(f"event:{name or 'start'}")
    if kind == "end":
        return _norm_key(f"end:{name or 'end'}")
    return _norm_key(f"{kind}:{name}")

def _edge_key(e: Dict[str, Any], nodes_by_id: Dict[str, Dict[str, Any]]) -> str:
    frm_raw = e.get("frm") or e.get("from")
    to_raw = e.get("to")
    frm = frm_raw if isinstance(frm_raw, str) else ""
    to = to_raw if isinstance(to_raw, str) else ""
    cond = (e.get("condition") or "").strip().lower()

    frm_key = _node_key(nodes_by_id.get(frm, {"kind": "unknown", "name": frm}))
    to_key  = _node_key(nodes_by_id.get(to, {"kind": "unknown", "name": to}))

    if cond:
        return f"{frm_key} ->|{cond}| {to_key}"
    return f"{frm_key} -> {to_key}"

def _unknown_key(u: Dict[str, Any]) -> str:
    return (u.get("question") or "").strip()

def diff_process(a_path: str, b_path: str, label_a: str = "A", label_b: str = "B") -> Dict[str, Any]:
    a = _load_json(a_path)
    b = _load_json(b_path)

    a_nodes: List[Dict[str, Any]] = a.get("nodes", [])
    b_nodes: List[Dict[str, Any]] = b.get("nodes", [])
    a_edges: List[Dict[str, Any]] = a.get("edges", [])
    b_edges: List[Dict[str, Any]] = b.get("edges", [])
    a_unknowns: List[Dict[str, Any]] = a.get("unknowns", [])
    b_unknowns: List[Dict[str, Any]] = b.get("unknowns", [])

    a_by_id: Dict[str, Dict[str, Any]] = {
        n["id"]: n for n in a_nodes if isinstance(n.get("id"), str)
    }
    b_by_id: Dict[str, Dict[str, Any]] = {
        n["id"]: n for n in b_nodes if isinstance(n.get("id"), str)
    }

    a_node_keys = {_node_key(n) for n in a_nodes}
    b_node_keys = {_node_key(n) for n in b_nodes}

    a_edge_keys = {_edge_key(e, a_by_id) for e in a_edges}
    b_edge_keys = {_edge_key(e, b_by_id) for e in b_edges}

    a_unk_keys = {_unknown_key(u) for u in a_unknowns if _unknown_key(u)}
    b_unk_keys = {_unknown_key(u) for u in b_unknowns if _unknown_key(u)}

    def evidence_rate(nodes: List[Dict[str, Any]]) -> float:
        if not nodes:
            return 0.0
        ok = 0
        for n in nodes:
            ev = n.get("evidence") or []
            if isinstance(ev, list) and len(ev) > 0:
                ok += 1
        return ok / len(nodes)

    def action_counts(nodes: List[Dict[str, Any]]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for n in nodes:
            act = (n.get("action") or {}).get("type")
            if act:
                k = act.upper()
                out[k] = out.get(k, 0) + 1
        return out

    diff_obj: Dict[str, Any] = {
        "inputs": {"a": a_path, "b": b_path, "label_a": label_a, "label_b": label_b},
        "summary": {
            "nodes": {"a": len(a_nodes), "b": len(b_nodes), "added_in_b": len(b_node_keys - a_node_keys), "removed_in_b": len(a_node_keys - b_node_keys)},
            "edges": {"a": len(a_edges), "b": len(b_edges), "added_in_b": len(b_edge_keys - a_edge_keys), "removed_in_b": len(a_edge_keys - b_edge_keys)},
            "unknowns": {"a": len(a_unknowns), "b": len(b_unknowns), "added_in_b": len(b_unk_keys - a_unk_keys), "removed_in_b": len(a_unk_keys - b_unk_keys)},
            "evidence_rate": {"a": evidence_rate(a_nodes), "b": evidence_rate(b_nodes)},
            "action_counts": {"a": action_counts(a_nodes), "b": action_counts(b_nodes)},
        },
        "details": {
            "nodes_added_in_b": sorted(list(b_node_keys - a_node_keys)),
            "nodes_removed_in_b": sorted(list(a_node_keys - b_node_keys)),
            "edges_added_in_b": sorted(list(b_edge_keys - a_edge_keys)),
            "edges_removed_in_b": sorted(list(a_edge_keys - b_edge_keys)),
            "unknowns_added_in_b": sorted(list(b_unk_keys - a_unk_keys)),
            "unknowns_removed_in_b": sorted(list(a_unk_keys - b_unk_keys)),
        }
    }
    return diff_obj

def diff_to_markdown(d: Dict[str, Any]) -> str:
    s = d["summary"]
    inp = d["inputs"]
    lines: List[str] = []
    lines.append(f"# Diff: {inp['label_a']} vs {inp['label_b']}")
    lines.append("")
    lines.append(f"- A: `{inp['a']}`")
    lines.append(f"- B: `{inp['b']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Nodes: A={s['nodes']['a']}  B={s['nodes']['b']}  (+{s['nodes']['added_in_b']} / -{s['nodes']['removed_in_b']})")
    lines.append(f"- Edges: A={s['edges']['a']}  B={s['edges']['b']}  (+{s['edges']['added_in_b']} / -{s['edges']['removed_in_b']})")
    lines.append(f"- Unknowns: A={s['unknowns']['a']}  B={s['unknowns']['b']}  (+{s['unknowns']['added_in_b']} / -{s['unknowns']['removed_in_b']})")
    lines.append(f"- Evidence coverage (node-level): A={s['evidence_rate']['a']:.2%}  B={s['evidence_rate']['b']:.2%}")
    lines.append("")
    lines.append("## Details")
    lines.append("")

    def section(title: str, items: List[str]):
        lines.append(f"### {title}")
        if not items:
            lines.append("- (none)")
        else:
            for it in items[:200]:
                lines.append(f"- {it}")
            if len(items) > 200:
                lines.append(f"- ... ({len(items)-200} more)")
        lines.append("")

    det = d["details"]
    section("Nodes added in B", det["nodes_added_in_b"])
    section("Nodes removed in B", det["nodes_removed_in_b"])
    section("Edges added in B", det["edges_added_in_b"])
    section("Edges removed in B", det["edges_removed_in_b"])
    section("Unknowns added in B", det["unknowns_added_in_b"])
    section("Unknowns removed in B", det["unknowns_removed_in_b"])

    return "\n".join(lines)

def write_diff(a_path: str, b_path: str, out_json: str, out_md: str, label_a: str, label_b: str) -> None:
    d = diff_process(a_path, b_path, label_a=label_a, label_b=label_b)
    Path(out_json).write_text(json.dumps(d, indent=2), encoding="utf-8")
    Path(out_md).write_text(diff_to_markdown(d), encoding="utf-8")
