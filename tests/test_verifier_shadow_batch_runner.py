"""
Tests for scripts/run_verifier_shadow_batch.py support utility.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_verifier_shadow_batch.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_verifier_shadow_batch", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_verifier_shadow_batch module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_diff_types_and_aggregate_summary():
    mod = _load_script_module()
    diff = {
        "valid_match": False,
        "codes_match": False,
        "provenance_top_level_compatible": True,
        "provenance_value_mismatches": ["vendor"],
    }
    types = mod.detect_diff_types(diff)
    assert types == ["valid_flag", "codes", "values"]

    summary = mod.aggregate_summary(
        [
            {"status": "no_diff", "diff_types": []},
            {"status": "diff", "diff_types": ["codes", "values"]},
            {"status": "diff", "diff_types": ["provenance"]},
            {"status": "error"},
        ]
    )
    assert summary == {
        "total_compared": 4,
        "no_diff": 1,
        "diff_valid_flag": 0,
        "diff_codes": 1,
        "diff_provenance": 1,
        "diff_values": 1,
        "error": 1,
    }


def test_run_shadow_batch_classifies_no_diff_and_diff():
    mod = _load_script_module()
    original = mod.run_verifier_shadow_comparison
    try:
        def _fake_shadow(raw_text: str, extraction: dict) -> dict:
            if extraction.get("force_diff"):
                return {
                    "legacy": {"valid": True, "codes": [], "provenance": {}},
                    "registry": {"valid": False, "codes": ["WRONG_TYPE"], "provenance": {}},
                    "diff": {
                        "has_diff": True,
                        "valid_match": False,
                        "codes_match": False,
                        "codes_only_in_legacy": [],
                        "codes_only_in_registry": ["WRONG_TYPE"],
                        "provenance_top_level_compatible": True,
                        "provenance_top_level_only_in_legacy": [],
                        "provenance_top_level_only_in_registry": [],
                        "provenance_value_mismatches": [],
                        "notes": ["valid flag differs", "failure code sequence differs"],
                    },
                }
            return {
                "legacy": {"valid": True, "codes": [], "provenance": {}},
                "registry": {"valid": True, "codes": [], "provenance": {}},
                "diff": {
                    "has_diff": False,
                    "valid_match": True,
                    "codes_match": True,
                    "codes_only_in_legacy": [],
                    "codes_only_in_registry": [],
                    "provenance_top_level_compatible": True,
                    "provenance_top_level_only_in_legacy": [],
                    "provenance_top_level_only_in_registry": [],
                    "provenance_value_mismatches": [],
                    "notes": [],
                },
            }

        mod.run_verifier_shadow_comparison = _fake_shadow
        results = mod.run_shadow_batch(
            [
                {"case_id": "a", "source": "x", "raw_text": "r1", "extraction": {}},
                {"case_id": "b", "source": "x", "raw_text": "r2", "extraction": {"force_diff": True}},
            ],
            verbose=False,
        )
        assert results[0]["status"] == "no_diff"
        assert results[1]["status"] == "diff"
        assert results[1]["diff_types"] == ["valid_flag", "codes"]
    finally:
        mod.run_verifier_shadow_comparison = original


def test_filter_logic_and_report_schema():
    mod = _load_script_module()
    rows = [
        {"case_id": "a", "source": "s", "status": "no_diff", "diff_types": []},
        {"case_id": "b", "source": "s", "status": "diff", "diff_types": ["codes"]},
        {"case_id": "c", "source": "s", "status": "diff", "diff_types": ["values"]},
    ]
    filtered = mod._apply_result_filters(
        rows,
        only_diffs=True,
        diff_types=["codes"],
        max_diffs=1,
    )
    assert [r["case_id"] for r in filtered] == ["b"]

    args = SimpleNamespace(
        only_diffs=False,
        diff_type=[],
        max_diffs=None,
        expected_jsonl=None,
        datasets_dir=Path("datasets"),
        input_json=None,
        input_jsonl=None,
        case_glob=[],
        case_id=[],
        limit=None,
        verbose=False,
    )
    report = mod._build_report(args=args, all_results=rows, emitted_results=rows)
    assert report["schema_version"] == "verifier_shadow_batch_report_v1"
    assert set(report["summary"].keys()) == {
        "total_compared",
        "no_diff",
        "diff_valid_flag",
        "diff_codes",
        "diff_provenance",
        "diff_values",
        "error",
    }

