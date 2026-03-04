"""
scripts/check_dataset_quotas.py
Deterministic dataset distribution quotas for the AP eval gold set.

Enforces stratified coverage rules so the dataset doesn't succumb to
"happy path" metric padding.  Pure Python — no LLM calls.

Usage
-----
    python scripts/check_dataset_quotas.py                # hard fail on violations
    python scripts/check_dataset_quotas.py --warn-only    # warnings only, exit 0
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QuotaResult:
    """Result of a single quota rule check."""
    rule_id: str
    description: str
    threshold: float
    direction: str       # "max" or "min"
    actual: float
    count: int
    total: int
    passed: bool


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRICKY_FORMAT_TAGS: frozenset[str] = frozenset({
    "multiple_totals", "weird_spacing", "table_like", "noisy_header",
})


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def check_quotas(records: list[dict]) -> list[QuotaResult]:
    """Evaluate all dataset quota rules against *records*.

    Returns a list of 4 QuotaResult objects (one per rule).
    """
    total = len(records)

    if total == 0:
        return [
            QuotaResult("a", "happy_path tag <= 50%", 0.50, "max", 0.0, 0, 0, False),
            QuotaResult("b", "EXCEPTION_NO_PO >= 10%", 0.10, "min", 0.0, 0, 0, False),
            QuotaResult("c", "EXCEPTION_MATCH_FAILED >= 10%", 0.10, "min", 0.0, 0, 0, False),
            QuotaResult("d", "tricky formatting tags >= 15%", 0.15, "min", 0.0, 0, 0, False),
        ]

    results: list[QuotaResult] = []

    # Rule a: happy_path <= 50%
    hp_count = sum(1 for r in records if "happy_path" in r.get("tags", []))
    hp_ratio = hp_count / total
    results.append(QuotaResult(
        rule_id="a",
        description="happy_path tag <= 50%",
        threshold=0.50,
        direction="max",
        actual=hp_ratio,
        count=hp_count,
        total=total,
        passed=hp_ratio <= 0.50,
    ))

    # Rule b: EXCEPTION_NO_PO >= 10%
    no_po_count = sum(
        1 for r in records
        if "EXCEPTION_NO_PO" in r.get("expected_status", [])
    )
    no_po_ratio = no_po_count / total
    results.append(QuotaResult(
        rule_id="b",
        description="EXCEPTION_NO_PO >= 10%",
        threshold=0.10,
        direction="min",
        actual=no_po_ratio,
        count=no_po_count,
        total=total,
        passed=no_po_ratio >= 0.10,
    ))

    # Rule c: EXCEPTION_MATCH_FAILED >= 10%
    mf_count = sum(
        1 for r in records
        if "EXCEPTION_MATCH_FAILED" in r.get("expected_status", [])
    )
    mf_ratio = mf_count / total
    results.append(QuotaResult(
        rule_id="c",
        description="EXCEPTION_MATCH_FAILED >= 10%",
        threshold=0.10,
        direction="min",
        actual=mf_ratio,
        count=mf_count,
        total=total,
        passed=mf_ratio >= 0.10,
    ))

    # Rule d: tricky formatting tags >= 15%
    tricky_count = sum(
        1 for r in records
        if TRICKY_FORMAT_TAGS.intersection(r.get("tags", []))
    )
    tricky_ratio = tricky_count / total
    results.append(QuotaResult(
        rule_id="d",
        description="tricky formatting tags >= 15%",
        threshold=0.15,
        direction="min",
        actual=tricky_ratio,
        count=tricky_count,
        total=total,
        passed=tricky_ratio >= 0.15,
    ))

    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_summary(results: list[QuotaResult]) -> None:
    """Print a clean terminal summary of quota results."""
    total = results[0].total if results else 0
    print(f"\nDataset Quota Check ({total} records)")
    print("-" * 60)
    print(f"  {'Rule':<6} {'Description':<35} {'Actual':<10} {'Required':<12} {'Status'}")
    print(f"  {'----':<6} {'-' * 35} {'-' * 9:<10} {'-' * 11:<12} {'------'}")

    for r in results:
        op = "<=" if r.direction == "max" else ">="
        status = "PASS" if r.passed else "FAIL"
        print(
            f"  {r.rule_id:<6} {r.description:<35} "
            f"{r.actual:.1%}{'':>4} {op} {r.threshold:.0%}{'':>5} {status}"
        )

    print("-" * 60)
    failed = [r for r in results if not r.passed]
    if failed:
        ids = ", ".join(r.rule_id for r in failed)
        print(f"  {len(failed)} rule(s) FAILED: {ids}")
    else:
        print("  All quotas satisfied.")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check dataset distribution quotas for the AP eval gold set",
    )
    parser.add_argument(
        "--expected", type=str, default="datasets/expected.jsonl",
        help="Path to expected.jsonl (default: datasets/expected.jsonl)",
    )
    parser.add_argument(
        "--warn-only", action="store_true",
        help="Print warnings instead of errors; exit 0 even if quotas fail",
    )
    args = parser.parse_args()

    from eval_runner import load_expected
    records = load_expected(args.expected)

    results = check_quotas(records)
    print_summary(results)

    if not all(r.passed for r in results):
        if args.warn_only:
            print("WARNING: Dataset quota violations detected (--warn-only mode).\n")
            sys.exit(0)
        else:
            print("ERROR: Dataset quota violations detected. Fix before proceeding.\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
