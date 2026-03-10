"""
Batch runner for verifier shadow comparisons (legacy vs registry path).

This utility is additive support tooling for RFC 3 cutover validation.
It does not modify production verifier behavior.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root importability when run as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.verifier_shadow import run_verifier_shadow_comparison

REPORT_SCHEMA_VERSION = "verifier_shadow_batch_report_v1"
DIFF_TYPE_CHOICES = ("valid_flag", "codes", "provenance", "values")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{idx} invalid JSON: {exc}") from exc
    return rows


def _build_case_from_obj(obj: dict, source: str, default_case_id: str) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{source}: case must be an object")
    case_id = str(obj.get("id") or obj.get("case_id") or default_case_id)
    raw_text = obj.get("raw_text")
    extraction = obj.get("extraction", obj.get("mock_extraction"))
    if not isinstance(raw_text, str):
        raise ValueError(f"{source}: case {case_id!r} missing string raw_text")
    if not isinstance(extraction, dict):
        raise ValueError(f"{source}: case {case_id!r} missing dict extraction/mock_extraction")
    return {
        "case_id": case_id,
        "source": source,
        "raw_text": raw_text,
        "extraction": extraction,
    }


def load_cases_from_expected_jsonl(expected_jsonl: Path, datasets_dir: Path) -> list[dict]:
    """Load cases from eval expected.jsonl + datasets/gold_invoices text files."""
    records = _load_jsonl(expected_jsonl)
    cases: list[dict] = []
    for idx, rec in enumerate(records, 1):
        case_id = str(rec.get("invoice_id") or f"expected_line_{idx}")
        filename = rec.get("file")
        extraction = rec.get("mock_extraction")
        if not isinstance(filename, str):
            raise ValueError(f"{expected_jsonl}:{idx} missing string file")
        if not isinstance(extraction, dict):
            raise ValueError(f"{expected_jsonl}:{idx} missing dict mock_extraction")
        raw_path = datasets_dir / "gold_invoices" / filename
        raw_text = raw_path.read_text(encoding="utf-8")
        cases.append(
            {
                "case_id": case_id,
                "source": f"expected_jsonl:{expected_jsonl}",
                "raw_text": raw_text,
                "extraction": extraction,
                "file": filename,
            }
        )
    return cases


def load_cases_from_input_json(input_json: Path) -> list[dict]:
    """Load one or many cases from JSON object/list."""
    payload = _load_json(input_json)
    if isinstance(payload, dict):
        return [_build_case_from_obj(payload, str(input_json), input_json.stem)]
    if isinstance(payload, list):
        cases: list[dict] = []
        for idx, row in enumerate(payload, 1):
            cases.append(
                _build_case_from_obj(
                    row,
                    source=f"{input_json}#{idx}",
                    default_case_id=f"{input_json.stem}_{idx}",
                )
            )
        return cases
    raise ValueError(f"{input_json}: top-level JSON must be object or list")


def load_cases_from_input_jsonl(input_jsonl: Path) -> list[dict]:
    """Load cases from JSONL (each row contains raw_text + extraction/mock_extraction)."""
    rows = _load_jsonl(input_jsonl)
    cases: list[dict] = []
    for idx, row in enumerate(rows, 1):
        cases.append(
            _build_case_from_obj(
                row,
                source=f"{input_jsonl}:{idx}",
                default_case_id=f"{input_jsonl.stem}_{idx}",
            )
        )
    return cases


def load_cases_from_globs(glob_patterns: list[str]) -> list[dict]:
    """Load cases from one or more glob patterns of JSON files."""
    files: set[str] = set()
    for pattern in glob_patterns:
        files.update(glob.glob(pattern, recursive=True))
    ordered = sorted(Path(f) for f in files)
    cases: list[dict] = []
    for path in ordered:
        if path.suffix.lower() != ".json":
            continue
        cases.extend(load_cases_from_input_json(path))
    return cases


def detect_diff_types(diff: dict) -> list[str]:
    """Classify diff dimensions for one shadow comparison result."""
    kinds: list[str] = []
    if not diff.get("valid_match", True):
        kinds.append("valid_flag")
    if not diff.get("codes_match", True):
        kinds.append("codes")
    if not diff.get("provenance_top_level_compatible", True):
        kinds.append("provenance")
    if bool(diff.get("provenance_value_mismatches", [])):
        kinds.append("values")
    return kinds


def aggregate_summary(case_results: list[dict]) -> dict:
    """Aggregate top-level summary counts."""
    summary = {
        "total_compared": 0,
        "no_diff": 0,
        "diff_valid_flag": 0,
        "diff_codes": 0,
        "diff_provenance": 0,
        "diff_values": 0,
        "error": 0,
    }
    for row in case_results:
        summary["total_compared"] += 1
        status = row.get("status")
        if status == "error":
            summary["error"] += 1
            continue
        if status == "no_diff":
            summary["no_diff"] += 1
            continue
        kinds = set(row.get("diff_types", []))
        if "valid_flag" in kinds:
            summary["diff_valid_flag"] += 1
        if "codes" in kinds:
            summary["diff_codes"] += 1
        if "provenance" in kinds:
            summary["diff_provenance"] += 1
        if "values" in kinds:
            summary["diff_values"] += 1
    return summary


def _apply_result_filters(
    case_results: list[dict],
    *,
    only_diffs: bool,
    diff_types: list[str],
    max_diffs: int | None,
) -> list[dict]:
    filtered = list(case_results)

    if only_diffs:
        filtered = [r for r in filtered if r.get("status") == "diff"]

    if diff_types:
        wanted = set(diff_types)
        filtered = [
            r for r in filtered
            if r.get("status") == "diff" and bool(wanted & set(r.get("diff_types", [])))
        ]

    if max_diffs is not None:
        limited: list[dict] = []
        seen_diffs = 0
        for row in filtered:
            if row.get("status") == "diff":
                if seen_diffs >= max_diffs:
                    continue
                seen_diffs += 1
            limited.append(row)
        filtered = limited

    return filtered


def run_shadow_batch(
    cases: list[dict],
    *,
    verbose: bool = False,
) -> list[dict]:
    """Run shadow comparisons over cases and return per-case results."""
    results: list[dict] = []
    for case in cases:
        case_id = str(case["case_id"])
        source = str(case["source"])
        try:
            comparison = run_verifier_shadow_comparison(
                raw_text=case["raw_text"],
                extraction=case["extraction"],
            )
            diff = comparison["diff"]
            diff_types = detect_diff_types(diff)
            status = "diff" if diff.get("has_diff") else "no_diff"
            row = {
                "case_id": case_id,
                "source": source,
                "status": status,
                "diff_types": diff_types,
                "diff": diff,
            }
            if "file" in case:
                row["file"] = case["file"]
            if verbose:
                row["legacy"] = comparison["legacy"]
                row["registry"] = comparison["registry"]
            results.append(row)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "case_id": case_id,
                    "source": source,
                    "status": "error",
                    "error": str(exc),
                }
            )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run batch verifier shadow comparisons (legacy vs registry).",
    )
    parser.add_argument(
        "--expected-jsonl",
        type=Path,
        default=None,
        help="Path to expected.jsonl (uses mock_extraction + datasets/gold_invoices text).",
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=Path("datasets"),
        help="Datasets root for --expected-jsonl mode (default: datasets).",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="Path to JSON object/list containing explicit shadow cases.",
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=None,
        help="Path to JSONL containing explicit shadow cases.",
    )
    parser.add_argument(
        "--case-glob",
        action="append",
        default=[],
        help="Glob pattern(s) for JSON case files (repeatable).",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Filter to specific case_id values (repeatable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of loaded cases after sorting.",
    )
    parser.add_argument(
        "--only-diffs",
        action="store_true",
        help="Show/report only cases with has_diff=true.",
    )
    parser.add_argument(
        "--diff-type",
        action="append",
        choices=DIFF_TYPE_CHOICES,
        default=[],
        help="Filter output to diffs containing this type (repeatable).",
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=None,
        help="Limit emitted diff cases to first N after filtering.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include legacy and registry payloads per case.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write machine-readable JSON report.",
    )
    return parser.parse_args()


def _build_report(
    *,
    args: argparse.Namespace,
    all_results: list[dict],
    emitted_results: list[dict],
) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "summary": aggregate_summary(all_results),
        "selection": {
            "total_loaded": len(all_results),
            "total_emitted": len(emitted_results),
            "only_diffs": args.only_diffs,
            "diff_types": list(args.diff_type),
            "max_diffs": args.max_diffs,
        },
        "run_options": {
            "expected_jsonl": str(args.expected_jsonl) if args.expected_jsonl else None,
            "datasets_dir": str(args.datasets_dir),
            "input_json": str(args.input_json) if args.input_json else None,
            "input_jsonl": str(args.input_jsonl) if args.input_jsonl else None,
            "case_glob": list(args.case_glob),
            "case_id": list(args.case_id),
            "limit": args.limit,
            "verbose": args.verbose,
            "argv": sys.argv,
        },
        "cases": emitted_results,
    }


def _print_summary(summary: dict) -> None:
    print("Verifier Shadow Batch Summary")
    print("-----------------------------")
    print(f"total_compared: {summary['total_compared']}")
    print(f"no_diff: {summary['no_diff']}")
    print(f"diff_valid_flag: {summary['diff_valid_flag']}")
    print(f"diff_codes: {summary['diff_codes']}")
    print(f"diff_provenance: {summary['diff_provenance']}")
    print(f"diff_values: {summary['diff_values']}")
    print(f"error: {summary['error']}")


def main() -> int:
    args = parse_args()

    if args.max_diffs is not None and args.max_diffs < 0:
        print("ERROR: --max-diffs must be >= 0", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 0:
        print("ERROR: --limit must be >= 0", file=sys.stderr)
        return 2

    cases: list[dict] = []
    try:
        if args.expected_jsonl:
            cases.extend(load_cases_from_expected_jsonl(args.expected_jsonl, args.datasets_dir))
        if args.input_json:
            cases.extend(load_cases_from_input_json(args.input_json))
        if args.input_jsonl:
            cases.extend(load_cases_from_input_jsonl(args.input_jsonl))
        if args.case_glob:
            cases.extend(load_cases_from_globs(args.case_glob))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed loading cases: {exc}", file=sys.stderr)
        return 2

    if not cases:
        print(
            "ERROR: no cases loaded. Provide at least one of "
            "--expected-jsonl / --input-json / --input-jsonl / --case-glob",
            file=sys.stderr,
        )
        return 2

    # Deterministic ordering.
    cases.sort(key=lambda c: (str(c.get("case_id", "")), str(c.get("source", ""))))

    if args.case_id:
        wanted = set(args.case_id)
        cases = [c for c in cases if c["case_id"] in wanted]
        missing = sorted(wanted - {c["case_id"] for c in cases})
        if missing:
            print(f"ERROR: unknown case_id(s): {missing}", file=sys.stderr)
            return 2

    if args.limit is not None:
        cases = cases[: args.limit]

    all_results = run_shadow_batch(cases, verbose=args.verbose)
    emitted_results = _apply_result_filters(
        all_results,
        only_diffs=args.only_diffs,
        diff_types=list(args.diff_type),
        max_diffs=args.max_diffs,
    )

    report = _build_report(args=args, all_results=all_results, emitted_results=emitted_results)
    _print_summary(report["summary"])
    print(f"emitted_cases: {len(emitted_results)}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Wrote JSON report: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
