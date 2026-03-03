"""
scripts/fix_graph.py
Manual normalization and deduplication tool for AP process graph JSON files.

Usage
-----
    python scripts/fix_graph.py <input.json> [<output.json>]

If output path is omitted, writes to ``<stem>_normalized.json`` next to
the input file.

What it does
------------
1. Normalizes all edge condition strings via ``normalize_condition()`` from
   the Condition DSL.  Unknown/ambiguous conditions are left unchanged and
   reported.
2. Deduplicates edges that become identical (frm, to, normalized_condition)
   after normalization — keeping the first occurrence.
3. Emits a human-readable report of all changes.
4. Writes the result to the output path.

This script does NOT run automatically.  It is a manual repair tool.
The linter remains the authoritative validity gate.

NOTE: This script does not attempt to infer missing branches.  If a
gateway condition cannot be normalised (returns None), it is left as-is
and flagged in the report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src is importable when run from project root or scripts/
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.conditions import normalize_condition
from src.linter import lint_process_graph


def fix_graph(input_path: str, output_path: str | None = None) -> None:
    """
    Normalize and deduplicate the graph JSON at *input_path*.

    Parameters
    ----------
    input_path  : path to input ap_*.json
    output_path : optional output path (defaults to ``<stem>_normalized.json``)
    """
    src = Path(input_path)
    if output_path is None:
        dst = src.with_name(src.stem + "_normalized.json")
    else:
        dst = Path(output_path)

    print(f"\n[fix_graph] Input  : {src}")
    data = json.loads(src.read_text(encoding="utf-8"))

    raw_edges: list[dict] = data.get("edges", [])
    report: list[str] = []
    changed: int = 0
    unknown_conditions: list[tuple[int, str]] = []

    # -----------------------------------------------------------------------
    # Pass 1 — normalize conditions
    # -----------------------------------------------------------------------
    for idx, edge in enumerate(raw_edges):
        raw = edge.get("condition")
        if raw is None:
            continue   # null conditions: not a string, skip

        norm = normalize_condition(raw)

        if norm is None:
            unknown_conditions.append((idx, raw))
            continue   # leave as-is; flag in report

        if norm != raw:
            report.append(
                f"  edge[{idx}] ({edge.get('frm')} → {edge.get('to')}): "
                f"{raw!r}  →  {norm!r}"
            )
            edge["condition"] = norm
            changed += 1

    # -----------------------------------------------------------------------
    # Pass 2 — deduplicate edges by (frm, to, condition) after normalization
    # -----------------------------------------------------------------------
    seen: dict[tuple[str, str, str | None], int] = {}
    deduped: list[dict] = []
    removed: int = 0

    for idx, edge in enumerate(raw_edges):
        key = (edge.get("frm", ""), edge.get("to", ""), edge.get("condition"))
        if key in seen:
            report.append(
                f"  edge[{idx}] ({edge.get('frm')} → {edge.get('to')}, "
                f"cond={edge.get('condition')!r}): REMOVED (duplicate of edge[{seen[key]}])"
            )
            removed += 1
        else:
            seen[key] = idx
            deduped.append(edge)

    data["edges"] = deduped

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n[fix_graph] Condition normalizations : {changed}")
    print(f"[fix_graph] Duplicate edges removed  : {removed}")

    if report:
        print("\n[fix_graph] Changes:")
        for line in report:
            print(line)

    if unknown_conditions:
        print(f"\n[fix_graph] WARNING — {len(unknown_conditions)} condition(s) could not be normalised:")
        for idx, raw in unknown_conditions:
            edge = raw_edges[idx]
            print(f"  edge[{idx}] ({edge.get('frm')} → {edge.get('to')}): {raw!r}")

    # -----------------------------------------------------------------------
    # Post-normalization lint (informational only; tool does not block)
    # -----------------------------------------------------------------------
    print("\n[fix_graph] Running linter on normalised graph…")
    errors = [e for e in lint_process_graph(data) if e.severity == "error"]
    warnings = [e for e in lint_process_graph(data) if e.severity == "warning"]

    if errors:
        print(f"  ⚠  {len(errors)} error(s) remain after normalisation:")
        for e in errors:
            print(f"     {e}")
    else:
        print("  ✓  No linter errors remain.")

    if warnings:
        print(f"  ℹ  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"     {w}")

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[fix_graph] Output : {dst}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_graph.py <input.json> [<output.json>]")
        sys.exit(1)

    _input  = sys.argv[1]
    _output = sys.argv[2] if len(sys.argv) >= 3 else None
    fix_graph(_input, _output)
