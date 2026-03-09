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
    python eval_runner.py --show-failures          # console failure summary
    python eval_runner.py --group-by-tag           # tag breakdown in markdown
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
from src.policy import DEFAULT_POLICY

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

_REQUIRED_EXTRACTION_FIELDS = frozenset(DEFAULT_POLICY.required_fields)


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
    """Casefold + whitespace collapse + trailing punctuation strip for vendor comparison."""
    return re.sub(r"\s+", " ", s).strip().casefold().rstrip(".,")


def compare_fields(expected_fields: dict, result_state: dict) -> dict:
    """Compare expected fields against actual result state.

    Returns {field: {"expected": ..., "actual": ..., "match": bool}}.
    """
    comparisons: dict[str, dict] = {}
    for field, expected in expected_fields.items():
        actual = result_state.get(field)
        if field == "vendor":
            match = _norm_str(str(expected)) == _norm_str(str(actual or ""))
        elif field in ("amount", "tax_amount"):
            match = actual is not None and abs(float(expected) - float(actual)) <= 0.01
        elif field == "invoice_date":
            match = str(expected) == str(actual or "")
        else:  # has_po: strict
            match = expected == actual
        comparisons[field] = {"expected": expected, "actual": actual, "match": match}
    return comparisons


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------
def classify_failure(status_match: bool, field_comparison: dict) -> dict:
    """Deterministic failure bucketing from comparison results.

    Returns dict with failure_bucket, field_mismatches, terminal_match.
    """
    field_mismatches = [
        f for f, c in field_comparison.items() if not c["match"]
    ]
    has_field_fail = len(field_mismatches) > 0

    if status_match and not has_field_fail:
        bucket = "pass"
    elif not status_match and not has_field_fail:
        bucket = "terminal_mismatch"
    elif status_match and has_field_fail:
        bucket = "field_mismatch"
    else:
        bucket = "both_terminal_and_field_mismatch"

    return {
        "failure_bucket": bucket,
        "field_mismatches": field_mismatches,
        "terminal_match": status_match,
    }


# ---------------------------------------------------------------------------
# Failure groupings
# ---------------------------------------------------------------------------
_FAILURE_BUCKETS = ("terminal_mismatch", "field_mismatch",
                    "both_terminal_and_field_mismatch")


def compute_failure_groupings(
    results: list[dict],
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    """Return (failures_by_bucket, failures_by_tag) from per-invoice results.

    failures_by_bucket always has all 3 bucket keys (stable shape).
    failures_by_tag only includes tags with ≥1 failure.
    """
    by_bucket: dict[str, list[str]] = {b: [] for b in _FAILURE_BUCKETS}
    tag_buckets: dict[str, dict[str, list[str]]] = {}

    for r in results:
        bucket = r.get("failure_bucket", "pass")
        if bucket == "pass":
            continue
        inv_id = r["invoice_id"]
        by_bucket[bucket].append(inv_id)

        for tag in r.get("tags", []):
            if tag not in tag_buckets:
                tag_buckets[tag] = {b: [] for b in _FAILURE_BUCKETS}
            tag_buckets[tag][bucket].append(inv_id)

    return by_bucket, tag_buckets


# ---------------------------------------------------------------------------
# Primary evaluation buckets (stratified reporting)
# ---------------------------------------------------------------------------
_PRIMARY_BUCKETS = (
    "noisy_ocr_synthetic",
    "match_path",
    "extended_fields",
    "clean_standard",
)


def classify_primary_bucket(
    tags: list[str], compared_field_names: set[str],
) -> str:
    """Assign exactly one primary evaluation bucket to a gold record.

    Classification is deterministic and priority-ordered:
    1. noisy_ocr_synthetic — has 'synthetic' tag
    2. match_path — has 'match_fail' tag (and not synthetic)
    3. extended_fields — has invoice_date or tax_amount in compared fields
    4. clean_standard — everything else
    """
    if "synthetic" in tags:
        return "noisy_ocr_synthetic"
    if "match_fail" in tags:
        return "match_path"
    if "invoice_date" in compared_field_names or "tax_amount" in compared_field_names:
        return "extended_fields"
    return "clean_standard"


def compute_bucket_metrics(results: list[dict]) -> dict[str, dict]:
    """Compute stratified metrics for each primary evaluation bucket.

    Each result must already have a ``primary_bucket`` key.
    Returns dict keyed by bucket name.  All ``_PRIMARY_BUCKETS`` keys are
    always present (stable shape).
    """
    grouped: dict[str, list[dict]] = {b: [] for b in _PRIMARY_BUCKETS}
    for r in results:
        grouped[r["primary_bucket"]].append(r)

    by_bucket: dict[str, dict] = {}
    for bucket in _PRIMARY_BUCKETS:
        cohort = grouped[bucket]
        count = len(cohort)
        terminal_correct = sum(1 for r in cohort if r["status_match"])

        field_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "total": 0},
        )
        overall_correct = 0
        overall_total = 0
        for r in cohort:
            for field, comp in r["field_comparison"].items():
                field_stats[field]["total"] += 1
                overall_total += 1
                if comp["match"]:
                    field_stats[field]["correct"] += 1
                    overall_correct += 1

        fa: dict[str, dict] = {}
        for field in sorted(field_stats.keys()):
            s = field_stats[field]
            fa[field] = {
                "correct": s["correct"],
                "total": s["total"],
                "accuracy": s["correct"] / s["total"] if s["total"] > 0 else 0.0,
            }
        fa["overall"] = {
            "correct": overall_correct,
            "total": overall_total,
            "accuracy": overall_correct / overall_total if overall_total > 0 else 0.0,
        }

        # Per-bucket failure breakdown
        fb: dict[str, list[str]] = {b: [] for b in _FAILURE_BUCKETS}
        for r in cohort:
            fbucket = r.get("failure_bucket", "pass")
            if fbucket != "pass":
                fb[fbucket].append(r["invoice_id"])

        by_bucket[bucket] = {
            "count": count,
            "terminal_accuracy": {
                "correct": terminal_correct,
                "total": count,
                "accuracy": terminal_correct / count if count > 0 else 0.0,
            },
            "field_accuracy": fa,
            "failure_breakdown": fb,
        }

    return by_bucket


# ---------------------------------------------------------------------------
# Trace assertion checks
# ---------------------------------------------------------------------------
def check_trace(audit_log: list, expected_trace: dict) -> dict:
    """Validate audit_log against expected_trace must_include/must_exclude.

    Parses each audit_log entry as JSON (falls back to plain text).
    Returns {must_include_passed, must_exclude_passed, missing, forbidden_found}.
    """
    must_include = expected_trace.get("must_include", [])
    must_exclude = expected_trace.get("must_exclude", [])

    # Parse audit log entries into structured data
    parsed_entries: list[dict] = []
    for entry in audit_log:
        if isinstance(entry, str):
            try:
                parsed_entries.append(json.loads(entry))
            except (json.JSONDecodeError, TypeError):
                pass  # plain text entry, skip
        elif isinstance(entry, dict):
            parsed_entries.append(entry)

    def _item_found(item: str) -> bool:
        """Check if item matches any parsed audit_log entry."""
        for e in parsed_entries:
            if e.get("event") == item:
                return True
            if e.get("from_node") == item:
                return True
            if e.get("selected") == item:
                return True
            if e.get("node") == item:
                return True
        return False

    missing = [item for item in must_include if not _item_found(item)]
    forbidden_found = [item for item in must_exclude if _item_found(item)]

    return {
        "must_include_passed": len(missing) == 0,
        "must_exclude_passed": len(forbidden_found) == 0,
        "missing": missing,
        "forbidden_found": forbidden_found,
    }


# ---------------------------------------------------------------------------
# Exit-code decision
# ---------------------------------------------------------------------------
def should_exit_zero(metrics: dict) -> bool:
    """Return True when both terminal and field accuracy are 100%."""
    ta = metrics["terminal_accuracy"]["accuracy"]
    fa = metrics["field_accuracy"]["overall"]["accuracy"]
    return ta == 1.0 and fa == 1.0


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

        failure_info = classify_failure(status_match, field_comparison)
        audit_log = final_state.get("audit_log", [])

        result_entry = {
            "invoice_id": rec["invoice_id"],
            "expected_status": rec["expected_status"],
            "actual_status": actual_status,
            "status_match": status_match,
            "field_comparison": field_comparison,
            "match_result": final_state.get("match_result", "UNKNOWN"),
            "tags": rec["tags"],
            "audit_log": audit_log,
            "failure_bucket": failure_info["failure_bucket"],
            "field_mismatches": failure_info["field_mismatches"],
            "extraction": final_state.get("extraction", {}),
            "raw_text": raw_text,
            "failure_codes": final_state.get("failure_codes", []),
        }

        # Optional trace checks
        if "expected_trace" in rec and rec["expected_trace"]:
            result_entry["trace_checks"] = check_trace(
                audit_log, rec["expected_trace"]
            )

        results.append(result_entry)

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

    # Tag-based cohort metrics
    all_tags: set[str] = set()
    for r in results:
        tags = r.get("tags", [])
        if not tags:
            tags = ["untagged"]
        all_tags.update(tags)

    by_tag: dict[str, dict] = {}
    for tag in sorted(all_tags):
        tagged = [r for r in results if tag in r.get("tags", ["untagged"])]
        tag_total = len(tagged)
        tag_terminal_correct = sum(1 for r in tagged if r["status_match"])

        tag_field_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "total": 0}
        )
        tag_overall_correct = 0
        tag_overall_total = 0
        for r in tagged:
            for field, comp in r["field_comparison"].items():
                tag_field_stats[field]["total"] += 1
                tag_overall_total += 1
                if comp["match"]:
                    tag_field_stats[field]["correct"] += 1
                    tag_overall_correct += 1

        tag_fa: dict[str, dict] = {}
        for field in sorted(tag_field_stats.keys()):
            s = tag_field_stats[field]
            tag_fa[field] = {
                "correct": s["correct"],
                "total": s["total"],
                "accuracy": s["correct"] / s["total"] if s["total"] > 0 else 0.0,
            }
        tag_fa["overall"] = {
            "correct": tag_overall_correct,
            "total": tag_overall_total,
            "accuracy": (tag_overall_correct / tag_overall_total
                         if tag_overall_total > 0 else 0.0),
        }

        by_tag[tag] = {
            "count": tag_total,
            "terminal_accuracy": {
                "correct": tag_terminal_correct,
                "total": tag_total,
                "accuracy": (tag_terminal_correct / tag_total
                             if tag_total > 0 else 0.0),
            },
            "field_accuracy": tag_fa,
        }

    # Primary bucket classification (stratified reporting)
    for r in results:
        r["primary_bucket"] = classify_primary_bucket(
            r.get("tags", []), set(r["field_comparison"].keys()),
        )
    by_primary_bucket = compute_bucket_metrics(results)

    # Failure groupings (stable shape — always present)
    failures_by_bucket, failures_by_tag = compute_failure_groupings(results)

    # Invariant signal checks + triage autopilot
    from eval_triage import compute_invariant_signals, generate_action_plan

    suspicious_passes: list[str] = []
    for r in results:
        # Parse LAST amount_candidates event from audit_log
        # (CRITIC_RETRY may emit multiple; last = final extraction state)
        amount_candidates_event = None
        for entry in r.get("audit_log", []):
            try:
                evt = json.loads(entry)
                if evt.get("event") == "amount_candidates":
                    amount_candidates_event = evt  # keep overwriting → last wins
            except (json.JSONDecodeError, TypeError):
                pass

        signals = compute_invariant_signals(
            r.get("raw_text", ""),
            r.get("extraction", {}),
            amount_candidates_event,
        )
        r["invariant_signals"] = signals

        # Suspicious pass: passed eval but invariant flags raised
        if r["failure_bucket"] == "pass" and len(signals) > 0:
            suspicious_passes.append(r["invoice_id"])

        # Action plan for failures and suspicious passes
        if r["failure_bucket"] != "pass" or len(signals) > 0:
            r["action_plan"] = generate_action_plan(
                bucket=r["failure_bucket"],
                failure_codes=r.get("failure_codes", []),
                signals=signals,
            )

    return {
        "field_accuracy": field_accuracy,
        "terminal_accuracy": {
            "correct": terminal_correct,
            "total": total,
            "accuracy": terminal_correct / total if total > 0 else 0.0,
        },
        "unknown_rate": unknown_rate,
        "confusion_matrix": confusion_plain,
        "by_tag": by_tag,
        "by_primary_bucket": by_primary_bucket,
        "failures_by_bucket": failures_by_bucket,
        "failures_by_tag": failures_by_tag,
        "suspicious_passes": suspicious_passes,
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


def write_md_report(
    metrics: dict, outpath: str | Path, *, group_by_tag: bool = False,
) -> None:
    """Write a Markdown summary report."""
    lines: list[str] = []
    lines.append("# Evaluation Report\n")

    # Stratified results (primary truth surface)
    bpb = metrics.get("by_primary_bucket")
    if bpb:
        lines.append("## Stratified Results\n")
        lines.append("| Bucket | Count | Terminal Accuracy | Field Accuracy |")
        lines.append("|--------|-------|-------------------|----------------|")
        for bucket in _PRIMARY_BUCKETS:
            data = bpb.get(bucket)
            if not data:
                continue
            bta = data["terminal_accuracy"]
            bfa = data["field_accuracy"].get("overall", {})
            lines.append(
                f"| {bucket} | {data['count']}"
                f" | {bta['correct']}/{bta['total']} ({bta['accuracy']:.1%})"
                f" | {bfa.get('correct', 0)}/{bfa.get('total', 0)}"
                f" ({bfa.get('accuracy', 0):.1%}) |"
            )
        lines.append("")

        # Per-bucket failure details
        has_bucket_failures = any(
            sum(len(v) for v in bpb[b]["failure_breakdown"].values()) > 0
            for b in _PRIMARY_BUCKETS if b in bpb
        )
        if has_bucket_failures:
            lines.append("### Per-Bucket Failures\n")
            for bucket in _PRIMARY_BUCKETS:
                data = bpb.get(bucket)
                if not data:
                    continue
                fb = data["failure_breakdown"]
                total_fb = sum(len(v) for v in fb.values())
                if total_fb == 0:
                    continue
                lines.append(f"**{bucket}** ({total_fb} failure(s)):\n")
                for fb_name in _FAILURE_BUCKETS:
                    ids = fb.get(fb_name, [])
                    if ids:
                        lines.append(f"- {fb_name}: {', '.join(ids)}")
                lines.append("")

        # Interpretation notes
        lines.append("### Interpretation Notes\n")
        lines.append(
            "> **clean_standard**: Standard invoices without special "
            "characteristics — primary benchmark cohort.\n>"
        )
        lines.append(
            "> **noisy_ocr_synthetic**: Synthetic OCR-noise stress cases; "
            "mock-mode results reflect extraction template fidelity, "
            "not real OCR robustness.\n>"
        )
        lines.append(
            "> **match_path**: 3-way PO match failure path; tests "
            "MATCH_3_WAY → exception routing.\n>"
        )
        lines.append(
            "> **extended_fields**: Invoices with invoice_date/tax_amount; "
            "small sample — directional, not statistically robust.\n"
        )

    # Aggregate metrics (blended — use stratified results as primary truth)
    lines.append("## Aggregate Metrics\n")
    lines.append(
        "> *Aggregate metrics blend standard, stress, extended-field, and "
        "workflow-path cases; use stratified results as the primary "
        "truth surface.*\n"
    )

    ta = metrics["terminal_accuracy"]
    lines.append(f"**Terminal Accuracy**: {ta['correct']}/{ta['total']}"
                 f" ({ta['accuracy']:.1%})\n")
    lines.append(f"**Unknown rate**: {metrics['unknown_rate']:.1%}\n")

    # Field accuracy table
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

    # Failures by bucket
    fbb = metrics.get("failures_by_bucket", {})
    total_failures = sum(len(v) for v in fbb.values())
    if total_failures > 0:
        lines.append("## Failures by Bucket\n")
        lines.append("| Bucket | Count | Invoice IDs |")
        lines.append("|--------|-------|-------------|")
        for bucket in _FAILURE_BUCKETS:
            ids = fbb.get(bucket, [])
            if ids:
                lines.append(f"| {bucket} | {len(ids)} | {', '.join(ids)} |")
        lines.append("")
    else:
        lines.append("## Failures\n")
        lines.append("No failures.\n")

    # Failures by tag
    fbt = metrics.get("failures_by_tag", {})
    if fbt:
        lines.append("## Failures by Tag\n")
        lines.append("| Tag | Bucket | Invoice IDs |")
        lines.append("|-----|--------|-------------|")
        for tag in sorted(fbt.keys()):
            for bucket in _FAILURE_BUCKETS:
                ids = fbt[tag].get(bucket, [])
                if ids:
                    lines.append(f"| {tag} | {bucket} | {', '.join(ids)} |")
        lines.append("")

    # Tag breakdown (optional)
    if group_by_tag and "by_tag" in metrics:
        lines.append("## Accuracy by Tag\n")
        lines.append("| Tag | Count | Terminal | Field (overall) |")
        lines.append("|-----|-------|----------|-----------------|")
        for tag, data in sorted(metrics["by_tag"].items()):
            ta_tag = data["terminal_accuracy"]
            fa_tag = data["field_accuracy"].get("overall", {})
            lines.append(
                f"| {tag} | {data['count']}"
                f" | {ta_tag['correct']}/{ta_tag['total']}"
                f" ({ta_tag['accuracy']:.1%})"
                f" | {fa_tag.get('correct', 0)}/{fa_tag.get('total', 0)}"
                f" ({fa_tag.get('accuracy', 0):.1%}) |"
            )
        lines.append("")

    # Suspicious passes
    sp = metrics.get("suspicious_passes", [])
    if sp:
        lines.append("## Suspicious Passes (Accidental Correctness)\n")
        lines.append("| Invoice | Signals |")
        lines.append("|---------|---------|")
        for r in metrics["per_invoice"]:
            if r["invoice_id"] in sp:
                sigs = ", ".join(r.get("invariant_signals", []))
                lines.append(f"| {r['invoice_id']} | {sigs} |")
        lines.append("")
    else:
        lines.append("## Suspicious Passes\n")
        lines.append("No suspicious passes detected.\n")

    # Triage action plans
    plans_by_owner: dict[str, list] = {}
    for r in metrics["per_invoice"]:
        ap = r.get("action_plan")
        if ap:
            owner = ap.get("owner", "unknown")
            plans_by_owner.setdefault(owner, []).append(r)
    if plans_by_owner:
        lines.append("## Triage Action Plans\n")
        for owner in sorted(plans_by_owner.keys()):
            items = plans_by_owner[owner]
            lines.append(f"### Owner: {owner} ({len(items)} invoice(s))\n")
            lines.append("| Invoice | Bucket | Signals | Next Steps | Files |")
            lines.append("|---------|--------|---------|------------|-------|")
            for r in items:
                ap = r["action_plan"]
                sigs = ", ".join(r.get("invariant_signals", []))
                steps = "; ".join(ap.get("recommended_next_steps", []))
                files = ", ".join(ap.get("likely_files", []))
                lines.append(
                    f"| {r['invoice_id']} | {r['failure_bucket']}"
                    f" | {sigs} | {steps} | {files} |"
                )
            lines.append("")

    # Variance & Fragility Report (only when variance data exists)
    variance_data = metrics.get("variance")
    if variance_data:
        lines.append("## Variance & Fragility Report\n")
        lines.append("| Invoice ID | Runs | Matches | Fragility Score | Unstable Fields |")
        lines.append("|------------|------|---------|-----------------|-----------------|")
        for vr in variance_data:
            unstable = ", ".join(vr["unstable_fields"]) or "none"
            score_pct = f"{vr['fragility_score']:.0%}"
            lines.append(
                f"| {vr['invoice_id']} | {vr['runs']} | {vr['matches']}"
                f" | {score_pct} | {unstable} |"
            )
        brittle = [v for v in variance_data if v["fragility_score"] < 1.0]
        if brittle:
            lines.append(
                f"\n> **WARNING**: {len(brittle)} invoice(s) showed extraction "
                "non-determinism."
            )
        lines.append("")

    # Per-invoice detail
    lines.append("## Per-Invoice Results\n")
    lines.append("| Invoice | Bucket | Expected | Actual | Match | Fields |")
    lines.append("|---------|--------|----------|--------|-------|--------|")
    for r in metrics["per_invoice"]:
        field_summary = ", ".join(
            f"{f}:{'ok' if c['match'] else 'FAIL'}"
            for f, c in r["field_comparison"].items()
        )
        status_icon = "ok" if r["status_match"] else "FAIL"
        pbucket = r.get("primary_bucket", "")
        lines.append(
            f"| {r['invoice_id']} | {pbucket} | {r['expected_status'][0]}"
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
    parser.add_argument("--group-by-tag", action="store_true",
                        help="Include tag breakdown table in markdown report")
    parser.add_argument("--show-failures", action="store_true",
                        help="Print console summary of failing invoices by bucket")
    # Audit layer flags (optional, advisory only)
    parser.add_argument("--audit", action="store_true",
                        help="Enable optional LLM audit layer")
    parser.add_argument("--audit-sample", type=int, default=5,
                        help="Number of passing invoices to audit (default: 5)")
    parser.add_argument("--audit-max", type=int, default=None,
                        help="Hard cap on total audited invoices")
    parser.add_argument("--audit-mode", type=str, default="failures_and_sample",
                        choices=["failures_and_sample", "failures_only", "sample_only"],
                        help="Audit target selection mode (default: failures_and_sample)")
    parser.add_argument("--audit-provider", type=str, default="ollama",
                        choices=["ollama", "openai"],
                        help="LLM provider for audit (default: ollama)")
    parser.add_argument("--audit-model", type=str, default=None,
                        help="Model name for audit (default: auto per provider)")
    parser.add_argument("--audit-timeout-secs", type=int, default=30,
                        help="Per-call timeout in seconds (default: 30)")
    parser.add_argument("--audit-output", type=str, default="eval_audit_report.json",
                        help="JSON output path for audit report")
    parser.add_argument("--audit-md-output", type=str, default="eval_audit_report.md",
                        help="Markdown output path for audit report")
    parser.add_argument("--audit-seed", type=int, default=1337,
                        help="PRNG seed for audit sample selection (default: 1337)")
    parser.add_argument("--variance-test", action="store_true",
                        help="Run variance (fragility) testing on a sample of invoices")
    parser.add_argument("--variance-runs", type=int, default=5,
                        help="Number of LLM calls per invoice for variance test (default: 5)")
    parser.add_argument("--variance-sample", type=int, default=3,
                        help="Number of invoices to sample for variance test (default: 3)")
    parser.add_argument("--variance-seed", type=int, default=42,
                        help="PRNG seed for variance sample selection (default: 42)")
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

    # Show failures grouped by bucket
    if args.show_failures:
        failures = [r for r in metrics["per_invoice"] if r["failure_bucket"] != "pass"]
        if failures:
            buckets: dict[str, list] = defaultdict(list)
            for r in failures:
                buckets[r["failure_bucket"]].append(r)
            print(f"\n  --- Failures ({len(failures)}) ---")
            for bucket, items in sorted(buckets.items()):
                print(f"\n  [{bucket}] ({len(items)} invoices):")
                for r in items:
                    mismatches = ", ".join(r.get("field_mismatches", [])) or "none"
                    print(f"    {r['invoice_id']}: "
                          f"expected={r['expected_status']}, "
                          f"actual={r['actual_status']}, "
                          f"field_mismatches=[{mismatches}]")
        else:
            print("\n  --- 0 failures ---")

    # Suspicious passes
    sp = metrics.get("suspicious_passes", [])
    if sp:
        print(f"  Suspicious passes: {len(sp)} ({', '.join(sp)})")

    # Variance testing (requires --live mode)
    if args.variance_test and not args.live:
        print("\n  [Warning] --variance-test requires --live mode. "
              "Skipping variance testing.")
    elif args.variance_test:
        import random as _random
        from eval_variance import run_variance_test

        rng = _random.Random(args.variance_seed)
        sample_size = min(args.variance_sample, len(gold_records))
        sampled = rng.sample(gold_records, sample_size)

        print(f"\n{'=' * 60}")
        print(f"  Variance Testing ({sample_size} invoices x {args.variance_runs} runs)")
        print(f"{'=' * 60}\n")

        variance_results = []
        for rec in sampled:
            raw_text = load_invoice_text(_DEFAULT_DATASETS_DIR, rec["file"])
            vr = run_variance_test(
                rec["invoice_id"], raw_text, rec, args.variance_runs,
            )
            variance_results.append(vr)
            score_pct = f"{vr['fragility_score']:.0%}"
            unstable = ", ".join(vr["unstable_fields"]) or "none"
            print(f"  {vr['invoice_id']}: {vr['matches']}/{vr['runs']} "
                  f"({score_pct}) unstable=[{unstable}]")

        metrics["variance"] = variance_results

        avg_score = (
            sum(v["fragility_score"] for v in variance_results) / len(variance_results)
            if variance_results else 0.0
        )
        brittle = [v for v in variance_results if v["fragility_score"] < 1.0]
        print(f"\n  Average fragility score: {avg_score:.0%}")
        if brittle:
            print(f"  WARNING: {len(brittle)} invoice(s) showed extraction "
                  "non-determinism")

    # Write reports
    write_json_report(metrics, "eval_report.json")
    write_md_report(metrics, "eval_report.md", group_by_tag=args.group_by_tag)
    print(f"\n[eval] Reports written: eval_report.json, eval_report.md")

    # Optional audit layer (advisory only — does NOT affect exit code)
    if args.audit:
        from eval_audit import run_audit, write_audit_md_report

        print(f"\n{'=' * 60}")
        print("  Audit Layer (advisory only)")
        print(f"{'=' * 60}\n")

        audit_metrics = run_audit(
            results=metrics["per_invoice"],
            gold_records=gold_records,
            datasets_dir=_DEFAULT_DATASETS_DIR,
            audit_mode=args.audit_mode,
            audit_sample=args.audit_sample,
            audit_seed=args.audit_seed,
            audit_max=args.audit_max,
            provider=args.audit_provider,
            model=args.audit_model,
            timeout_secs=args.audit_timeout_secs,
        )
        write_json_report(audit_metrics, args.audit_output)
        write_audit_md_report(audit_metrics, args.audit_md_output)
        print(f"\n[audit] Reports written: {args.audit_output}, {args.audit_md_output}")

    # Exit code: non-zero if terminal or field accuracy < 100%
    sys.exit(0 if should_exit_zero(metrics) else 1)


if __name__ == "__main__":
    main()
