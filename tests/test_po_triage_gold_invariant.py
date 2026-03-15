"""
tests/test_po_triage_gold_invariant.py
Gold-label regression tests for the PO triage routing invariant (PO_TRIAGE_001).

This module encodes the invariant directly — no imports from the discovery
sandbox.  It validates that every gold record in datasets/expected.jsonl
has an expected_status consistent with the deterministic triage rule:

    if not has_po          → EXCEPTION_NO_PO
    elif not po_match      → EXCEPTION_MATCH_FAILED
    else (has_po & match)  → APPROVED or PAID

The test requires only the gold dataset; no runtime graph artifact is needed.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Inline invariant logic (deliberately duplicated — no sandbox dependency)
# ---------------------------------------------------------------------------

_EXPECTED_STATUS_MAP: dict[str, set[str]] = {
    "no_po":                      {"EXCEPTION_NO_PO"},
    "po_present_match_failed":    {"EXCEPTION_MATCH_FAILED"},
    "po_present_match_succeeded": {"APPROVED", "PAID"},
}


def _assign_cohort(record: dict) -> str:
    """Assign a PO triage cohort based on has_po and po_match fields."""
    has_po = record.get("expected_fields", {}).get("has_po", False)
    po_match = record.get("po_match", False)
    if not has_po:
        return "no_po"
    if not po_match:
        return "po_present_match_failed"
    return "po_present_match_succeeded"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_gold_records() -> list[dict]:
    path = Path("datasets") / "expected.jsonl"
    records: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


_GOLD_RECORDS = _load_gold_records()


# ===========================================================================
# TestPOTriageGoldInvariant — parametrized over every gold record
# ===========================================================================

class TestPOTriageGoldInvariant:
    """Each gold record's expected_status must be consistent with the triage rule."""

    @pytest.mark.parametrize(
        "record",
        [pytest.param(r, id=r["invoice_id"]) for r in _GOLD_RECORDS],
    )
    def test_gold_record_matches_triage_rule(self, record: dict) -> None:
        cohort = _assign_cohort(record)
        allowed = _EXPECTED_STATUS_MAP[cohort]
        actual = set(record["expected_status"])
        assert actual.issubset(allowed), (
            f"{record['invoice_id']}: cohort={cohort}, "
            f"expected_status={record['expected_status']}, "
            f"allowed={sorted(allowed)}"
        )


# ===========================================================================
# TestPOTriageCohortCoverage — aggregate invariant checks
# ===========================================================================

class TestPOTriageCohortCoverage:

    def test_all_three_cohorts_represented(self) -> None:
        cohorts = {_assign_cohort(r) for r in _GOLD_RECORDS}
        assert cohorts == set(_EXPECTED_STATUS_MAP.keys()), (
            f"Missing cohorts: {set(_EXPECTED_STATUS_MAP.keys()) - cohorts}"
        )

    def test_zero_contradictions(self) -> None:
        contradictions = []
        for r in _GOLD_RECORDS:
            cohort = _assign_cohort(r)
            allowed = _EXPECTED_STATUS_MAP[cohort]
            if not set(r["expected_status"]).issubset(allowed):
                contradictions.append(r["invoice_id"])
        assert len(contradictions) == 0, (
            f"{len(contradictions)} contradiction(s): {contradictions}"
        )


# ===========================================================================
# TestPOTriageCohortDistribution — curated distribution sanity checks
# ===========================================================================

class TestPOTriageCohortDistribution:

    @pytest.fixture(autouse=True)
    def _cohort_counts(self) -> None:
        self.counts: Counter[str] = Counter(
            _assign_cohort(r) for r in _GOLD_RECORDS
        )

    def test_no_po_cohort_count(self) -> None:
        assert self.counts["no_po"] == 24

    def test_match_failed_cohort_count(self) -> None:
        assert self.counts["po_present_match_failed"] == 17

    def test_match_succeeded_cohort_count(self) -> None:
        assert self.counts["po_present_match_succeeded"] == 85
