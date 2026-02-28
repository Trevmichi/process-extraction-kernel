from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _canonical_keys(doc: dict) -> Set[str]:
    return {n["meta"]["canonical_key"] for n in doc["nodes"]}


def _edge_key_pairs(doc: dict) -> Set[Tuple[str, str, str]]:
    """Return set of (canonical_frm, canonical_to, condition) triples."""
    id_to_key: Dict[str, str] = {n["id"]: n["meta"]["canonical_key"] for n in doc["nodes"]}
    pairs: Set[Tuple[str, str, str]] = set()
    for e in doc.get("edges", []):
        frm = id_to_key.get(e["frm"], e["frm"])
        to = id_to_key.get(e["to"], e["to"])
        cond = (e.get("condition") or "").strip()
        pairs.add((frm, to, cond))
    return pairs


# Keys that are structural bookmarks, not process intents — skip in step comparison
_SKIP_KEYS = {"event:start", "end:end"}


def run_gap_analysis(output_dir: str = "outputs") -> str:
    master = _load(f"{output_dir}/ap_master_manual_auto.json")
    master_keys = _canonical_keys(master)
    master_edges = _edge_key_pairs(master)

    doc_ids = ["doc_001", "doc_002", "doc_003", "doc_004", "doc_005"]

    lines: List[str] = [
        "# Gap Analysis Report",
        "",
        "Comparison of each sub-document's auto-extracted process against the "
        "Master Manual (`ap_master_manual_auto`).",
        "",
        "> **Missing Step** — intent present in the sub-document but absent from the Master Manual.",
        "> **Missing Logic Path** — directed edge (A → B) present in the sub-document but absent from the Master Manual.",
        "",
    ]

    for doc_id in doc_ids:
        doc = _load(f"{output_dir}/ap_{doc_id}_auto.json")
        doc_keys = _canonical_keys(doc)
        doc_edges = _edge_key_pairs(doc)

        extra_steps = sorted(doc_keys - master_keys - _SKIP_KEYS)
        extra_edges = sorted(doc_edges - master_edges)

        lines.append(f"## {doc_id}")
        lines.append("")

        # --- Step gaps ---
        lines.append("### Steps present in sub-doc but absent from Master Manual")
        lines.append("")
        if extra_steps:
            lines.append("| # | Canonical Key |")
            lines.append("|---|---------------|")
            for i, key in enumerate(extra_steps, 1):
                lines.append(f"| {i} | `{key}` |")
        else:
            lines.append("_None — all step intents are covered by the Master Manual._")
        lines.append("")

        # --- Edge gaps ---
        lines.append("### Logic paths present in sub-doc but absent from Master Manual")
        lines.append("")
        if extra_edges:
            lines.append("| # | From (canonical) | To (canonical) | Condition |")
            lines.append("|---|------------------|----------------|-----------|")
            for i, (frm, to, cond) in enumerate(extra_edges, 1):
                cond_str = f"`{cond}`" if cond else "_(unconditional)_"
                lines.append(f"| {i} | `{frm}` | `{to}` | {cond_str} |")
        else:
            lines.append("_None — all logic paths are covered by the Master Manual._")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_gap_analysis(output_dir: str = "outputs") -> str:
    report = run_gap_analysis(output_dir)
    out_path = Path(output_dir) / "gap_analysis_report.md"
    out_path.write_text(report, encoding="utf-8")
    return str(out_path)
