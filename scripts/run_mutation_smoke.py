"""
Run a curated deterministic-layer mutation smoke campaign.

Phase 1 design goals:
- Curated and low-noise (small domain-specific catalog)
- One mutant at a time
- Explicit outcome categories: killed / survived / error / skipped
- Always restore source state after each mutant run
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_VERSION = "mutation_smoke_v1"
REPORT_SCHEMA_VERSION = "mutation_smoke_report_v1"
VALID_STATUSES = {"killed", "survived", "error", "skipped"}
VALID_CATEGORIES = {"conditions", "router", "verifier", "linter_invariants"}


def _load_catalog_module(catalog_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("mutation_catalog", catalog_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load catalog module from {catalog_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_mutant_catalog(catalog_path: Path | None = None) -> list[dict]:
    """Load and validate mutant catalog data."""
    path = catalog_path or Path(__file__).with_name("mutation_catalog.py")
    module = _load_catalog_module(path)
    catalog = getattr(module, "MUTATION_CATALOG", None)
    if not isinstance(catalog, list):
        raise ValueError("Catalog module must export MUTATION_CATALOG as a list.")

    required = {
        "id",
        "target_file",
        "description",
        "mutation_type",
        "apply_rule",
        "pytest_commands",
        "expected_rationale",
    }

    seen_ids: set[str] = set()
    for idx, mutant in enumerate(catalog):
        if not isinstance(mutant, dict):
            raise ValueError(f"Catalog entry at index {idx} is not a dict.")
        missing = required - set(mutant.keys())
        if missing:
            raise ValueError(f"Mutant {mutant.get('id', idx)!r} missing keys: {sorted(missing)}")
        mid = str(mutant["id"])
        if mid in seen_ids:
            raise ValueError(f"Duplicate mutant id: {mid}")
        seen_ids.add(mid)
        if not isinstance(mutant["pytest_commands"], list):
            raise ValueError(f"Mutant {mid} pytest_commands must be a list.")
        for command in mutant["pytest_commands"]:
            if not isinstance(command, list) or not all(isinstance(p, str) for p in command):
                raise ValueError(f"Mutant {mid} has invalid pytest command: {command!r}")
        if "category" in mutant:
            category = str(mutant["category"]).strip().lower()
            if category not in VALID_CATEGORIES:
                raise ValueError(
                    f"Mutant {mid} has invalid category {mutant['category']!r}; "
                    f"expected one of {sorted(VALID_CATEGORIES)}"
                )
    return catalog


def infer_mutant_category(mutant: dict) -> str:
    """Return normalized mutant category."""
    explicit = mutant.get("category")
    if explicit is not None:
        return str(explicit).strip().lower()

    target_file = str(mutant.get("target_file", "")).replace("\\", "/")
    if target_file.endswith("src/conditions.py"):
        return "conditions"
    if target_file.endswith("src/agent/router.py"):
        return "router"
    if target_file.endswith("src/verifier.py"):
        return "verifier"
    return "linter_invariants"


def normalize_category(category: str) -> str:
    normalized = category.strip().lower().replace("-", "_")
    if normalized not in VALID_CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid categories: {sorted(VALID_CATEGORIES)}"
        )
    return normalized


def select_mutants(
    catalog: list[dict],
    include_ids: list[str] | None = None,
    categories: list[str] | None = None,
    max_mutants: int | None = None,
) -> list[dict]:
    """Filter catalog by IDs and optional max-mutants budget."""
    selected = catalog
    if include_ids:
        wanted = set(include_ids)
        selected = [m for m in catalog if m["id"] in wanted]
        missing = wanted - {m["id"] for m in selected}
        if missing:
            raise ValueError(f"Unknown mutant id(s): {sorted(missing)}")

    if categories:
        normalized_categories = [normalize_category(c) for c in categories]
        selected = [
            m for m in selected
            if infer_mutant_category(m) in set(normalized_categories)
        ]

    if max_mutants is not None:
        if max_mutants < 0:
            raise ValueError("--max-mutants must be >= 0")
        selected = selected[:max_mutants]

    return selected


def _copy_workspace(src_root: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Create a disposable workspace copy for mutation runs."""
    tmpdir = tempfile.TemporaryDirectory(prefix="mutation-smoke-")
    dst_root = Path(tmpdir.name) / "workspace"
    ignore = shutil.ignore_patterns(
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        ".venv",
        "outputs",
    )
    shutil.copytree(src_root, dst_root, ignore=ignore)
    return tmpdir, dst_root


def _apply_replace_one(text: str, old: str, new: str) -> tuple[str | None, str | None]:
    count = text.count(old)
    if count == 0:
        return None, "pattern not found"
    if count > 1:
        return None, f"pattern matched {count} locations (expected exactly 1)"
    return text.replace(old, new, 1), None


def apply_mutation_text(original_text: str, apply_rule: dict) -> tuple[str | None, str | None]:
    """Apply a mutation rule to file contents and return (mutated_text, reason)."""
    kind = apply_rule.get("kind")
    if kind == "replace_one":
        old = apply_rule.get("old")
        new = apply_rule.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            return None, "replace_one requires string 'old' and 'new'"
        return _apply_replace_one(original_text, old, new)
    return None, f"unsupported apply_rule kind: {kind!r}"


def _tail_output(output: str, max_lines: int = 30) -> str:
    lines = output.strip().splitlines()
    if not lines:
        return ""
    tail = lines[-max_lines:]
    return "\n".join(tail)


def _run_pytest_commands(
    pytest_commands: list[list[str]],
    workspace_root: Path,
    python_executable: str,
    timeout_seconds: float,
) -> tuple[str, dict]:
    """Run per-mutant pytest commands and classify outcome."""
    last_run: dict[str, Any] = {}
    for command_args in pytest_commands:
        cmd = [python_executable, "-m", "pytest", *command_args]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            last_run = {
                "command": cmd,
                "return_code": None,
                "duration_seconds": round(duration, 3),
                "reason": f"pytest timeout after {timeout_seconds:.1f}s",
                "stdout_tail": _tail_output(exc.stdout or ""),
                "stderr_tail": _tail_output(exc.stderr or ""),
            }
            last_run["outcome_stage"] = "pytest"
            return "error", last_run

        duration = time.perf_counter() - started
        last_run = {
            "command": cmd,
            "return_code": proc.returncode,
            "duration_seconds": round(duration, 3),
            "stdout_tail": _tail_output(proc.stdout),
            "stderr_tail": _tail_output(proc.stderr),
        }

        if proc.returncode == 0:
            continue
        if proc.returncode == 1:
            # "python -m pytest" can also return 1 when pytest is not installed.
            # That is an infrastructure issue, not a killed mutant.
            if "No module named pytest" in (proc.stderr or ""):
                last_run["reason"] = "pytest is not installed in selected interpreter"
                last_run["outcome_stage"] = "pytest"
                return "error", last_run
            last_run["reason"] = "pytest reported failing tests (mutant killed)"
            last_run["outcome_stage"] = "pytest"
            return "killed", last_run
        last_run["reason"] = f"pytest exited with unexpected return code {proc.returncode}"
        last_run["outcome_stage"] = "pytest"
        return "error", last_run

    last_run["reason"] = "all configured pytest commands passed"
    last_run["outcome_stage"] = "pytest"
    return "survived", last_run


def run_single_mutant(
    mutant: dict,
    workspace_root: Path,
    python_executable: str,
    timeout_seconds: float,
    dry_run: bool = False,
) -> dict:
    """Execute one mutant and return result record."""
    started = time.perf_counter()
    result: dict[str, Any] = {
        "id": mutant["id"],
        "category": infer_mutant_category(mutant),
        "status": "skipped",
        "target_file": mutant["target_file"],
        "mutation_type": mutant["mutation_type"],
        "description": mutant["description"],
        "pytest_commands": mutant["pytest_commands"],
        "expected_rationale": mutant["expected_rationale"],
        "duration_seconds": 0.0,
    }

    if dry_run:
        result["reason"] = "dry-run (not executed)"
        result["outcome_stage"] = "selection"
        result["duration_seconds"] = round(time.perf_counter() - started, 3)
        return result

    target_path = workspace_root / mutant["target_file"]
    if not target_path.exists():
        result["reason"] = f"target file missing in workspace copy: {mutant['target_file']}"
        result["outcome_stage"] = "mutation_apply"
        result["duration_seconds"] = round(time.perf_counter() - started, 3)
        return result

    original_text = target_path.read_text(encoding="utf-8")
    mutated_text: str | None = None
    try:
        mutated_text, reason = apply_mutation_text(original_text, mutant["apply_rule"])
        if mutated_text is None:
            result["reason"] = f"mutation skipped: {reason}"
            result["outcome_stage"] = "mutation_apply"
            return result

        target_path.write_text(mutated_text, encoding="utf-8")
        status, run_info = _run_pytest_commands(
            pytest_commands=mutant["pytest_commands"],
            workspace_root=workspace_root,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
        result["status"] = status
        result.update(run_info)
        if status not in VALID_STATUSES:
            result["status"] = "error"
            result["reason"] = f"internal error: unknown status {status!r}"
            result["outcome_stage"] = "internal"
    finally:
        if mutated_text is not None:
            target_path.write_text(original_text, encoding="utf-8")

    result["duration_seconds"] = round(time.perf_counter() - started, 3)
    return result


def build_report(
    results: list[dict],
    workspace_root: Path | None,
    dry_run: bool,
    run_metadata: dict | None = None,
) -> dict:
    """Create report payload with stable schema."""
    summary = {
        "total": len(results),
        "killed": sum(1 for r in results if r.get("status") == "killed"),
        "survived": sum(1 for r in results if r.get("status") == "survived"),
        "error": sum(1 for r in results if r.get("status") == "error"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "version": REPORT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "workspace_root": str(workspace_root) if workspace_root is not None else None,
        "summary": summary,
        "run_metadata": run_metadata or {},
        "results": results,
    }


def _print_list(mutants: list[dict], list_format: str = "text") -> None:
    rows = [
        {
            "id": m["id"],
            "category": infer_mutant_category(m),
            "mutation_type": m["mutation_type"],
            "target_file": m["target_file"],
            "description": m["description"],
        }
        for m in mutants
    ]
    if list_format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
        return

    print(f"Catalog size: {len(mutants)} mutant(s)")
    for row in rows:
        print(
            f"- {row['id']} [{row['category']}]: {row['mutation_type']} "
            f"({row['target_file']})"
        )


def _print_summary(report: dict) -> None:
    summary = report["summary"]
    print("\nMutation Smoke Report")
    print("---------------------")
    print(
        f"total={summary['total']} "
        f"killed={summary['killed']} "
        f"survived={summary['survived']} "
        f"error={summary['error']} "
        f"skipped={summary['skipped']}"
    )
    for row in report["results"]:
        status = str(row.get("status", "error")).upper()
        print(f"[{status:<8}] {row.get('id')}  {row.get('description')}")
        reason = row.get("reason")
        if reason:
            print(f"  reason: {reason}")
        if row.get("command"):
            print(f"  command: {' '.join(row['command'])}")
            print(f"  return_code: {row.get('return_code')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run curated deterministic-layer mutation smoke tests "
            "(RFC 4 Phase 1 scaffold)."
        ),
        epilog=(
            "Examples:\n"
            "  python scripts/run_mutation_smoke.py --dry-run --max-mutants 5\n"
            "  python scripts/run_mutation_smoke.py --mutant-id M005_router_conditional_cardinality_weakened\n"
            "  python scripts/run_mutation_smoke.py --category verifier --max-mutants 2 --json-out outputs/mutation_report.json\n"
            "  python scripts/run_mutation_smoke.py --list-mutants --list-format json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=None,
        help="Path to a Python catalog file exporting MUTATION_CATALOG.",
    )
    parser.add_argument(
        "--mutant-id",
        action="append",
        default=[],
        help="Run only the specified mutant ID (repeatable).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help=(
            "Filter by category (repeatable): "
            "conditions, router, verifier, linter_invariants"
        ),
    )
    parser.add_argument(
        "--max-mutants",
        type=int,
        default=None,
        help="Run at most N mutants from the selected set.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not mutate files or run pytest; emit planned entries as skipped.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional output path for JSON report.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Per pytest command timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--python-executable",
        type=str,
        default=sys.executable,
        help="Python executable used to run pytest (default: current interpreter).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List catalog mutants and exit (kept for backward compatibility).",
    )
    parser.add_argument(
        "--list-mutants",
        action="store_true",
        help="List catalog mutants and exit.",
    )
    parser.add_argument(
        "--list-format",
        choices=("text", "json"),
        default="text",
        help="Output format for --list / --list-mutants (default: text).",
    )
    return parser.parse_args()


def main() -> int:
    started = time.perf_counter()
    run_started_utc = datetime.now(timezone.utc)
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent

    try:
        catalog = load_mutant_catalog(args.catalog_path)
        selected = select_mutants(
            catalog,
            include_ids=args.mutant_id,
            categories=args.category,
            max_mutants=args.max_mutants,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.list or args.list_mutants:
        _print_list(selected, args.list_format)
        return 0

    workspace_ctx: tempfile.TemporaryDirectory[str] | None = None
    workspace_root: Path | None = None
    if not args.dry_run:
        workspace_ctx, workspace_root = _copy_workspace(project_root)

    try:
        results: list[dict] = []
        for mutant in selected:
            result = run_single_mutant(
                mutant=mutant,
                workspace_root=workspace_root or project_root,
                python_executable=args.python_executable,
                timeout_seconds=args.timeout_seconds,
                dry_run=args.dry_run,
            )
            results.append(result)

        run_finished_utc = datetime.now(timezone.utc)
        report = build_report(
            results,
            workspace_root,
            args.dry_run,
            run_metadata={
                "python_executable": args.python_executable,
                "argv": sys.argv,
                "catalog_path": str(args.catalog_path) if args.catalog_path else None,
                "filters": {
                    "mutant_ids": args.mutant_id,
                    "categories": [normalize_category(c) for c in args.category],
                    "max_mutants": args.max_mutants,
                },
                "run_started_utc": run_started_utc.isoformat(),
                "run_finished_utc": run_finished_utc.isoformat(),
                "duration_seconds": round(time.perf_counter() - started, 3),
            },
        )
        _print_summary(report)

        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print(f"\nWrote JSON report to {args.json_out}")
    finally:
        if workspace_ctx is not None:
            workspace_ctx.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
