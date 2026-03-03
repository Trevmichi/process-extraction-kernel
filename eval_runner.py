"""
eval_runner.py
Evaluation harness for the AP extraction pipeline.

Loads gold invoice records from ``datasets/expected.jsonl``, runs each through
the compiled LangGraph agent (with a deterministic mock LLM by default), and
produces field-accuracy / terminal-status reports.

Usage
-----
    python eval_runner.py                          # mock LLM (deterministic)
    python eval_runner.py --live                   # real Ollama
    python eval_runner.py --expected path/to.jsonl # custom expected
    python eval_runner.py --graph path/to.json     # custom graph
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from src.agent.compiler import build_ap_graph
from src.agent.state import APState, make_initial_state

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_EXPECTED = Path("datasets/expected.jsonl")
_DEFAULT_GRAPH = Path("outputs/ap_master_manual_auto_patched.json")
_DEFAULT_DATASETS_DIR = Path("datasets")

# Invoice-ID regex for mock dispatch
_INVOICE_ID_RE = re.compile(r"(INV-\d{4}|NR-\d{4}|TG-\d{4}|GLC-\d{4}|APX-\d{4})")


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------
_REQUIRED_RECORD_KEYS = frozenset({
    "invoice_id", "file", "po_match", "expected_status",
    "expected_fields", "mock_extraction", "tags",
})

_REQUIRED_EXTRACTION_FIELDS = frozenset({"vendor", "amount", "has_po"})


def _validate_gold_record(rec: dict) -> None:
    """Raise ValueError if *rec* is missing required keys or has wrong types."""
    missing = _REQUIRED_RECORD_KEYS - set(rec.keys())
    if missing:
        raise ValueError(
            f"Gold record {rec.get('invoice_id', '?')!r} missing keys: {sorted(missing)}"
        )
    if not isinstance(rec["expected_status"], list) or len(rec["expected_status"]) == 0:
        raise ValueError(
            f"Gold record {rec['invoice_id']!r}: expected_status must be a non-empty list"
        )
    me = rec["mock_extraction"]
    me_missing = _REQUIRED_EXTRACTION_FIELDS - set(me.keys())
    if me_missing:
        raise ValueError(
            f"Gold record {rec['invoice_id']!r}: mock_extraction missing: {sorted(me_missing)}"
        )


def load_expected(jsonl_path: str | Path) -> list[dict]:
    """Parse JSONL file and validate each record."""
    path = Path(jsonl_path)
    records: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {i} in {path}: invalid JSON: {exc}") from exc
        _validate_gold_record(rec)
        records.append(rec)
    return records


def load_invoice_text(datasets_dir: Path, filename: str) -> str:
    """Read an invoice text file from the gold_invoices directory."""
    path = datasets_dir / "gold_invoices" / filename
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Mock dispatch
# ---------------------------------------------------------------------------
def build_mock_dispatch(gold_records: list[dict]) -> Callable[[str], dict]:
    """Build a per-invoice mock LLM that dispatches by invoice_id in prompt.

    Raises ValueError if no invoice ID is found (fail-fast, no silent fallback).
    """
    lookup: dict[str, dict] = {}
    for rec in gold_records:
        lookup[rec["invoice_id"]] = rec["mock_extraction"]

    def mock(prompt: str) -> dict:
        if "validator" in prompt.lower():
            return {"is_valid": True}
        m = _INVOICE_ID_RE.search(prompt)
        if m and m.group(1) in lookup:
            return lookup[m.group(1)]
        raise ValueError(
            f"Mock dispatch: no known invoice ID found in prompt: {prompt[:120]!r}"
        )

    return mock


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------
def _norm_str(s: str) -> str:
    """Casefold + whitespace collapse for vendor comparison."""
    return re.sub(r"\s+", " ", s).strip().casefold()


def compare_fields(expected_fields: dict, result_state: dict) -> dict:
    """Compare expected fields against actual result state.

    Returns {field: {"expected": ..., "actual": ..., "match": bool}}.
    """
    comparisons: dict[str, dict] = {}
    for field, expected in expected_fields.items():
        actual = result_state.get(field)
        if field == "vendor":
            match = _norm_str(str(expected)) == _norm_str(str(actual or ""))
        elif field == "amount":
            match = abs(float(expected) - float(actual or 0)) <= 0.01
        else:  # has_po: strict
            match = expected == actual
        comparisons[field] = {"expected": expected, "actual": actual, "match": match}
    return comparisons


# ---------------------------------------------------------------------------
# Evaluation loop
# ---------------------------------------------------------------------------
def run_eval(
    graph,
    gold_records: list[dict],
    datasets_dir: Path,
    mock_dispatch: Callable[[str], dict] | None,
) -> list[dict]:
    """Run each gold invoice through the graph and collect results.

    Returns a list of per-invoice result dicts.
    """
    results: list[dict] = []

    for rec in gold_records:
        raw_text = load_invoice_text(datasets_dir, rec["file"])
        initial_state: APState = make_initial_state(
            invoice_id=rec["invoice_id"],
            raw_text=raw_text,
            po_match=rec["po_match"],
        )

        if mock_dispatch is not None:
            with patch("src.agent.nodes._call_llm_json", side_effect=mock_dispatch):
                final_state: APState = graph.invoke(initial_state)
        else:
            final_state = graph.invoke(initial_state)

        field_comparison = compare_fields(rec["expected_fields"], final_state)
        actual_status = final_state.get("status", "UNKNOWN")
        status_match = actual_status in rec["expected_status"]

        results.append({
            "invoice_id": rec["invoice_id"],
            "expected_status": rec["expected_status"],
            "actual_status": actual_status,
            "status_match": status_match,
            "field_comparison": field_comparison,
            "match_result": final_state.get("match_result", "UNKNOWN"),
            "tags": rec["tags"],
            "audit_log": final_state.get("audit_log", []),
        })

    return results


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_metrics(results: list[dict]) -> dict:
    """Aggregate per-invoice results into summary metrics."""
    total = len(results)

    # Terminal accuracy
    terminal_correct = sum(1 for r in results if r["status_match"])

    # Field accuracy
    field_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    overall_correct = 0
    overall_total = 0
    for r in results:
        for field, comp in r["field_comparison"].items():
            field_stats[field]["total"] += 1
            overall_total += 1
            if comp["match"]:
                field_stats[field]["correct"] += 1
                overall_correct += 1

    field_accuracy: dict[str, dict] = {}
    for field in sorted(field_stats.keys()):
        s = field_stats[field]
        field_accuracy[field] = {
            "correct": s["correct"],
            "total": s["total"],
            "accuracy": s["correct"] / s["total"] if s["total"] > 0 else 0.0,
        }
    field_accuracy["overall"] = {
        "correct": overall_correct,
        "total": overall_total,
        "accuracy": overall_correct / overall_total if overall_total > 0 else 0.0,
    }

    # Unknown rate
    unknown_count = sum(1 for r in results if r["match_result"] == "UNKNOWN")
    unknown_rate = unknown_count / total if total > 0 else 0.0

    # Confusion matrix: expected_primary x actual
    confusion_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        expected_primary = r["expected_status"][0]
        actual = r["actual_status"]
        confusion_matrix[expected_primary][actual] += 1

    # Convert defaultdicts to plain dicts for JSON serialization
    confusion_plain: dict[str, dict[str, int]] = {
        k: dict(v) for k, v in sorted(confusion_matrix.items())
    }

    return {
        "field_accuracy": field_accuracy,
        "terminal_accuracy": {
            "correct": terminal_correct,
            "total": total,
            "accuracy": terminal_correct / total if total > 0 else 0.0,
        },
        "unknown_rate": unknown_rate,
        "confusion_matrix": confusion_plain,
        "per_invoice": results,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------
def write_json_report(metrics: dict, outpath: str | Path) -> None:
    """Write metrics as JSON."""
    Path(outpath).write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_md_report(metrics: dict, outpath: str | Path) -> None:
    """Write a Markdown summary report."""
    lines: list[str] = []
    lines.append("# Evaluation Report\n")

    # Terminal accuracy
    ta = metrics["terminal_accuracy"]
    lines.append(f"## Terminal Accuracy: {ta['correct']}/{ta['total']}"
                 f" ({ta['accuracy']:.1%})\n")

    # Unknown rate
    lines.append(f"**Unknown rate**: {metrics['unknown_rate']:.1%}\n")

    # Field accuracy table
    lines.append("## Field Accuracy\n")
    lines.append("| Field | Correct | Total | Accuracy |")
    lines.append("|-------|---------|-------|----------|")
    for field, stats in metrics["field_accuracy"].items():
        lines.append(
            f"| {field} | {stats['correct']} | {stats['total']}"
            f" | {stats['accuracy']:.1%} |"
        )
    lines.append("")

    # Confusion matrix
    lines.append("## Confusion Matrix\n")
    cm = metrics["confusion_matrix"]
    all_statuses = sorted(set(
        s for row in cm.values() for s in row.keys()
    ) | set(cm.keys()))

    header = "| Expected \\ Actual | " + " | ".join(all_statuses) + " |"
    sep = "|" + "---|" * (len(all_statuses) + 1)
    lines.append(header)
    lines.append(sep)
    for expected in sorted(cm.keys()):
        row_counts = [str(cm[expected].get(s, 0)) for s in all_statuses]
        lines.append(f"| {expected} | " + " | ".join(row_counts) + " |")
    lines.append("")

    # Per-invoice detail
    lines.append("## Per-Invoice Results\n")
    lines.append("| Invoice | Expected | Actual | Match | Fields |")
    lines.append("|---------|----------|--------|-------|--------|")
    for r in metrics["per_invoice"]:
        field_summary = ", ".join(
            f"{f}:{'ok' if c['match'] else 'FAIL'}"
            for f, c in r["field_comparison"].items()
        )
        status_icon = "ok" if r["status_match"] else "FAIL"
        lines.append(
            f"| {r['invoice_id']} | {r['expected_status'][0]}"
            f" | {r['actual_status']} | {status_icon} | {field_summary} |"
        )
    lines.append("")

    Path(outpath).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="AP Extraction Evaluation Runner")
    parser.add_argument("--live", action="store_true",
                        help="Use real Ollama LLM instead of mock")
    parser.add_argument("--expected", type=str, default=str(_DEFAULT_EXPECTED),
                        help="Path to expected.jsonl")
    parser.add_argument("--graph", type=str, default=str(_DEFAULT_GRAPH),
                        help="Path to patched graph JSON")
    parser.add_argument("--filter", type=str, default=None,
                        help="Comma-separated invoice IDs to run (e.g. NR-2003,GLC-4003)")
    args = parser.parse_args()

    print(f"{'=' * 60}")
    print("  AP Extraction Pipeline — Evaluation Runner")
    print(f"  Expected: {args.expected}")
    print(f"  Graph:    {args.graph}")
    print(f"  Mode:     {'LIVE (Ollama)' if args.live else 'MOCK (deterministic)'}")
    if args.filter:
        print(f"  Filter:   {args.filter}")
    print(f"{'=' * 60}\n")

    # Load gold records
    gold_records = load_expected(args.expected)
    if args.filter:
        keep = {s.strip() for s in args.filter.split(",")}
        gold_records = [r for r in gold_records if r["invoice_id"] in keep]
    print(f"[eval] Loaded {len(gold_records)} gold records")

    # Compile graph
    graph = build_ap_graph(args.graph)
    print("[eval] Graph compiled successfully")

    # Build mock or use None for live
    mock_dispatch = None if args.live else build_mock_dispatch(gold_records)

    # Run evaluation
    print(f"[eval] Running {len(gold_records)} invoices ...\n")
    results = run_eval(graph, gold_records, _DEFAULT_DATASETS_DIR, mock_dispatch)

    # Compute metrics
    metrics = compute_metrics(results)

    # Print summary
    ta = metrics["terminal_accuracy"]
    fa = metrics["field_accuracy"].get("overall", {})
    print(f"  Terminal accuracy: {ta['correct']}/{ta['total']} ({ta['accuracy']:.1%})")
    print(f"  Field accuracy:    {fa.get('correct', 0)}/{fa.get('total', 0)}"
          f" ({fa.get('accuracy', 0):.1%})")
    print(f"  Unknown rate:      {metrics['unknown_rate']:.1%}")

    # Write reports
    write_json_report(metrics, "eval_report.json")
    write_md_report(metrics, "eval_report.md")
    print(f"\n[eval] Reports written: eval_report.json, eval_report.md")

    # Exit code: non-zero if terminal accuracy < 100%
    sys.exit(0 if ta["accuracy"] == 1.0 else 1)


if __name__ == "__main__":
    main()
