from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "run_mutation_smoke.py"


def _load_runner_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_mutation_smoke", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_mutation_smoke module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_catalog_loads_with_required_schema():
    runner = _load_runner_module()
    catalog = runner.load_mutant_catalog()

    assert 10 <= len(catalog) <= 20
    required = {
        "id",
        "target_file",
        "description",
        "mutation_type",
        "apply_rule",
        "pytest_commands",
        "expected_rationale",
    }
    for mutant in catalog:
        assert required.issubset(mutant.keys())


def test_dry_run_emits_skipped_and_json_schema(tmp_path: Path):
    json_out = tmp_path / "mutation_report.json"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--dry-run",
        "--max-mutants",
        "2",
        "--json-out",
        str(json_out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json_out.exists()

    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["version"] == "mutation_smoke_v1"
    assert report["schema_version"] == "mutation_smoke_report_v1"
    assert isinstance(report["generated_at_utc"], str)
    assert report["dry_run"] is True
    assert isinstance(report["run_metadata"], dict)
    assert "python_executable" in report["run_metadata"]
    assert "filters" in report["run_metadata"]
    assert "duration_seconds" in report["run_metadata"]

    summary = report["summary"]
    assert set(summary.keys()) == {"total", "killed", "survived", "error", "skipped"}
    assert summary["total"] == 2
    assert summary["skipped"] == 2
    assert summary["killed"] == 0
    assert summary["survived"] == 0
    assert summary["error"] == 0

    assert isinstance(report["results"], list)
    assert len(report["results"]) == 2
    first = report["results"][0]
    assert set(first.keys()) >= {
        "id",
        "category",
        "status",
        "target_file",
        "mutation_type",
        "description",
        "outcome_stage",
        "pytest_commands",
        "expected_rationale",
        "duration_seconds",
    }


def test_restore_executes_even_when_pytest_errors(tmp_path: Path):
    runner = _load_runner_module()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target_file = workspace / "dummy_target.py"
    original_text = "FLAG = True\n"
    target_file.write_text(original_text, encoding="utf-8")

    mutant = {
        "id": "T001_restore_guard",
        "target_file": "dummy_target.py",
        "description": "temporary test mutant",
        "mutation_type": "test",
        "apply_rule": {
            "kind": "replace_one",
            "old": "FLAG = True",
            "new": "FLAG = False",
        },
        "pytest_commands": [["--definitely-not-a-real-pytest-option"]],
        "expected_rationale": "pytest should error and file should still restore",
    }

    result = runner.run_single_mutant(
        mutant=mutant,
        workspace_root=workspace,
        python_executable=sys.executable,
        timeout_seconds=20.0,
        dry_run=False,
    )

    assert result["status"] == "error"
    assert target_file.read_text(encoding="utf-8") == original_text


def test_list_mutants_json_output_shape():
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--list-mutants",
        "--list-format",
        "json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert isinstance(rows, list)
    assert len(rows) >= 10
    first = rows[0]
    assert set(first.keys()) == {
        "id",
        "category",
        "mutation_type",
        "target_file",
        "description",
    }


def test_category_filtering_dry_run(tmp_path: Path):
    json_out = tmp_path / "category_report.json"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--dry-run",
        "--category",
        "verifier",
        "--json-out",
        str(json_out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["summary"]["total"] > 0
    for row in report["results"]:
        assert row["category"] == "verifier"


def test_invalid_mutant_id_returns_clear_error():
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--mutant-id",
        "M999_not_real",
        "--dry-run",
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "Unknown mutant id(s)" in proc.stderr


def test_dry_run_preserves_catalog_order(tmp_path: Path):
    json_out = tmp_path / "ordered_report.json"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--dry-run",
        "--max-mutants",
        "3",
        "--json-out",
        str(json_out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    ids = [row["id"] for row in report["results"]]
    assert ids == [
        "M001_conditions_reject_gt_to_gte",
        "M002_conditions_approve_lte_to_lt",
        "M003_conditions_has_po_synonym_flip",
    ]
