"""
tests/test_dataset_tools.py
Unit tests for dataset quota checking logic (scripts/check_dataset_quotas.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_dataset_quotas import QuotaResult, check_quotas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    invoice_id: str = "T-0001",
    tags: list[str] | None = None,
    expected_status: list[str] | None = None,
) -> dict:
    """Build a minimal gold record dict for quota testing."""
    return {
        "invoice_id": invoice_id,
        "file": "test.txt",
        "po_match": True,
        "expected_status": expected_status or ["APPROVED", "PAID"],
        "expected_fields": {"vendor": "X", "amount": 1.0, "has_po": True},
        "mock_extraction": {
            "vendor": {"value": "X", "evidence": "X"},
            "amount": {"value": 1.0, "evidence": "1.0"},
            "has_po": {"value": True, "evidence": "PO: X"},
        },
        "tags": tags or [],
    }


def _balanced_dataset() -> list[dict]:
    """20 records meeting all 4 quotas.

    Distribution:
      10 happy_path (50%)
       3 EXCEPTION_NO_PO (15%)
       3 EXCEPTION_MATCH_FAILED (15%)
       4 tricky formatting (20%) — none are happy_path
    """
    records: list[dict] = []
    # 10 happy_path (50% of 20 → exactly at limit)
    for i in range(10):
        records.append(_make_record(f"T-{i:04d}", tags=["happy_path"]))
    # 3 EXCEPTION_NO_PO (15%)
    for i in range(10, 13):
        records.append(_make_record(
            f"T-{i:04d}",
            tags=["no_po"],
            expected_status=["EXCEPTION_NO_PO"],
        ))
    # 3 EXCEPTION_MATCH_FAILED (15%)
    for i in range(13, 16):
        records.append(_make_record(
            f"T-{i:04d}",
            tags=["match_fail"],
            expected_status=["EXCEPTION_MATCH_FAILED"],
        ))
    # 4 tricky formatting (20%)
    for i, tag in enumerate(
        ["table_like", "weird_spacing", "multiple_totals", "noisy_header"], 16
    ):
        records.append(_make_record(f"T-{i:04d}", tags=[tag]))
    return records


# ===========================================================================
# TestQuotasAllPass
# ===========================================================================

class TestQuotasAllPass:

    def test_all_quotas_pass(self):
        results = check_quotas(_balanced_dataset())
        failed = [r for r in results if not r.passed]
        assert failed == [], f"Expected all pass, failed: {failed}"

    def test_returns_four_results(self):
        results = check_quotas(_balanced_dataset())
        assert len(results) == 4
        assert [r.rule_id for r in results] == ["a", "b", "c", "d"]

    def test_result_structure(self):
        results = check_quotas(_balanced_dataset())
        for r in results:
            assert isinstance(r, QuotaResult)
            assert r.rule_id in ("a", "b", "c", "d")
            assert r.direction in ("max", "min")
            assert 0.0 <= r.actual <= 1.0
            assert r.total == 20


# ===========================================================================
# Individual rule failure tests
# ===========================================================================

class TestQuotaRuleAFails:

    def test_happy_path_over_50_percent(self):
        """11/20 happy_path (55%) → rule a fails."""
        records = [_make_record(f"T-{i:04d}", tags=["happy_path"]) for i in range(11)]
        records += [_make_record(f"T-{i:04d}", tags=["no_po"],
                                 expected_status=["EXCEPTION_NO_PO"]) for i in range(11, 14)]
        records += [_make_record(f"T-{i:04d}", tags=["match_fail"],
                                 expected_status=["EXCEPTION_MATCH_FAILED"]) for i in range(14, 17)]
        records += [_make_record(f"T-{i:04d}", tags=["table_like"]) for i in range(17, 20)]

        results = check_quotas(records)
        rule_a = next(r for r in results if r.rule_id == "a")
        assert rule_a.passed is False
        assert rule_a.actual > 0.50


class TestQuotaRuleBFails:

    def test_no_po_under_10_percent(self):
        """1/20 EXCEPTION_NO_PO (5%) → rule b fails."""
        records = [_make_record(f"T-{i:04d}", tags=["happy_path"]) for i in range(9)]
        records += [_make_record("T-0009", tags=["no_po"],
                                 expected_status=["EXCEPTION_NO_PO"])]
        records += [_make_record(f"T-{i:04d}", tags=["match_fail"],
                                 expected_status=["EXCEPTION_MATCH_FAILED"]) for i in range(10, 14)]
        records += [_make_record(f"T-{i:04d}", tags=["table_like"]) for i in range(14, 20)]

        results = check_quotas(records)
        rule_b = next(r for r in results if r.rule_id == "b")
        assert rule_b.passed is False
        assert rule_b.actual < 0.10


class TestQuotaRuleCFails:

    def test_match_failed_under_10_percent(self):
        """0/20 EXCEPTION_MATCH_FAILED → rule c fails."""
        records = [_make_record(f"T-{i:04d}", tags=["happy_path"]) for i in range(8)]
        records += [_make_record(f"T-{i:04d}", tags=["no_po"],
                                 expected_status=["EXCEPTION_NO_PO"]) for i in range(8, 12)]
        records += [_make_record(f"T-{i:04d}", tags=["table_like"]) for i in range(12, 20)]

        results = check_quotas(records)
        rule_c = next(r for r in results if r.rule_id == "c")
        assert rule_c.passed is False
        assert rule_c.count == 0


class TestQuotaRuleDFails:

    def test_tricky_format_under_15_percent(self):
        """2/20 tricky format (10%) → rule d fails."""
        records = [_make_record(f"T-{i:04d}", tags=["happy_path"]) for i in range(8)]
        records += [_make_record(f"T-{i:04d}", tags=["no_po"],
                                 expected_status=["EXCEPTION_NO_PO"]) for i in range(8, 12)]
        records += [_make_record(f"T-{i:04d}", tags=["match_fail"],
                                 expected_status=["EXCEPTION_MATCH_FAILED"]) for i in range(12, 16)]
        # Only 2 tricky (10% < 15%)
        records += [_make_record(f"T-{i:04d}", tags=["table_like"]) for i in range(16, 18)]
        records += [_make_record(f"T-{i:04d}", tags=["other"]) for i in range(18, 20)]

        results = check_quotas(records)
        rule_d = next(r for r in results if r.rule_id == "d")
        assert rule_d.passed is False
        assert rule_d.actual < 0.15


# ===========================================================================
# Edge cases
# ===========================================================================

class TestQuotaEdgeCases:

    def test_empty_dataset(self):
        """Empty list → 4 failing results, no crash."""
        results = check_quotas([])
        assert len(results) == 4
        assert all(not r.passed for r in results)
        assert all(r.total == 0 for r in results)

    def test_boundary_exact_50_percent_happy_path(self):
        """Exactly 50% happy_path → PASS (rule a uses <=)."""
        records = _balanced_dataset()  # 10/20 = exactly 50%
        results = check_quotas(records)
        rule_a = next(r for r in results if r.rule_id == "a")
        assert rule_a.passed is True
        assert rule_a.actual == 0.50

    def test_multiple_tricky_tags_counted_once(self):
        """A record with both table_like and weird_spacing counts as 1 tricky record."""
        records = [_make_record(f"T-{i:04d}", tags=["happy_path"]) for i in range(5)]
        records += [_make_record(f"T-{i:04d}", tags=["no_po"],
                                 expected_status=["EXCEPTION_NO_PO"]) for i in range(5, 7)]
        records += [_make_record(f"T-{i:04d}", tags=["match_fail"],
                                 expected_status=["EXCEPTION_MATCH_FAILED"]) for i in range(7, 9)]
        # 1 record with multiple tricky tags
        records += [_make_record("T-0009", tags=["table_like", "weird_spacing"])]
        # 1/10 = 10% < 15% → still fails
        results = check_quotas(records)
        rule_d = next(r for r in results if r.rule_id == "d")
        assert rule_d.count == 1  # not double-counted


# ===========================================================================
# --warn-only mode (integration test via subprocess)
# ===========================================================================

class TestWarnOnlyMode:

    def test_warn_only_exits_zero_on_failure(self):
        """Quota check with --warn-only should exit 0 even when quotas fail."""
        result = subprocess.run(
            [sys.executable, "scripts/check_dataset_quotas.py", "--warn-only"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        )
        # Current dataset fails rules a+d, but --warn-only → exit 0
        assert result.returncode == 0
        assert "WARNING" in result.stdout or "FAIL" in result.stdout

    def test_without_warn_only_exits_nonzero_on_failure(self):
        """Quota check without --warn-only should exit 1 when quotas fail.

        Uses a temp JSONL with an imbalanced dataset to guarantee failure.
        """
        import tempfile, json
        # Build a dataset that fails rule a (100% happy_path)
        records = [
            _make_record(f"T-{i:04d}", tags=["happy_path"])
            for i in range(10)
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8",
        ) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "scripts/check_dataset_quotas.py",
                 "--expected", tmp_path],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent.parent),
            )
            assert result.returncode == 1
            assert "ERROR" in result.stdout
        finally:
            Path(tmp_path).unlink(missing_ok=True)
