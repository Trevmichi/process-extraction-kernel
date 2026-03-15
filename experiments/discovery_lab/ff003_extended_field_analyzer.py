"""
ff003_extended_field_analyzer.py
Diagnostic trace for FF-003 (extended-field extraction failure).

FF-003 covers the 7 INV-107x records that include invoice_date and
tax_amount in expected_fields.  6 of the 7 are blocked; INV-1076 passes.

This module traces each case through the full 5-step validation pipeline
and then extracts per-field diagnostic detail from the verifier provenance.
The goal is to identify the specific failure code(s) blocking each case
so that the taxonomy can be updated with confirmed (not hypothesized)
failure mechanisms.

No production code is modified.  All validators are imported read-only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Repo bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.discovery_lab.cohort_loader import (
    gold_invoice_dir,
    load_expected_records,
)
from src.arithmetic import check_arithmetic
from src.contracts import validate_extraction_semantics, validate_extraction_structure
from src.schema_validator import validate_payload
from src.verifier import verify_extraction, _normalize_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FF_003_IDS: frozenset[str] = frozenset(
    {"INV-1070", "INV-1071", "INV-1072", "INV-1073", "INV-1074", "INV-1075"}
)

POSITIVE_CONTROL_ID: str = "INV-1076"

ALL_TRACE_IDS: frozenset[str] = FF_003_IDS | {POSITIVE_CONTROL_ID}


# ---------------------------------------------------------------------------
# Core trace — full pipeline
# ---------------------------------------------------------------------------


def trace_full_pipeline(raw_text: str, extraction: dict) -> dict:
    """Run each validation step individually, recording per-step results.

    Same pattern as ff002_validation_trace.trace_validation_path — traces
    all 5 steps without short-circuiting.
    """
    trace: dict = {}

    # Step 1: Structural
    struct_ok, struct_issues = validate_extraction_structure(extraction)
    trace["structural"] = {"pass": struct_ok, "codes": struct_issues}

    # Step 2: Semantic (skip if structural failed)
    if struct_ok:
        sem_ok, sem_issues = validate_extraction_semantics(extraction)
        trace["semantic"] = {"pass": sem_ok, "codes": sem_issues}
    else:
        trace["semantic"] = {"pass": None, "codes": [], "skipped": "structural_failed"}

    # Step 3: Schema
    schema_errors = validate_payload(extraction, "extraction_payload_v1.json")
    trace["schema"] = {"pass": len(schema_errors) == 0, "codes": schema_errors}

    # Step 4: Verifier (always run for diagnostic completeness)
    valid, codes, prov = verify_extraction(raw_text, extraction)
    trace["verifier"] = {
        "pass": valid,
        "codes": [str(c) for c in codes],
        "provenance": prov,
    }

    # Step 5: Arithmetic (raw-text based, extraction-independent)
    arith_codes, arith_prov = check_arithmetic(raw_text)
    trace["arithmetic"] = {
        "pass": len(arith_codes) == 0,
        "codes": arith_codes,
        "check_ran": arith_prov is not None,
    }

    # First blocker in pipeline order
    pipeline_order = ["structural", "semantic", "schema", "verifier", "arithmetic"]
    first_blocker = None
    for step in pipeline_order:
        if trace[step].get("skipped"):
            continue
        if trace[step]["pass"] is False:
            first_blocker = step
            break
    trace["first_blocker"] = first_blocker
    trace["would_pass_pipeline"] = first_blocker is None

    return trace


# ---------------------------------------------------------------------------
# Per-field diagnostic extraction (from verifier provenance)
# ---------------------------------------------------------------------------


def extract_date_diagnostic(
    extraction: dict, prov: dict, verifier_codes: list[str],
) -> dict:
    """Extract per-field diagnostic detail for invoice_date from provenance."""
    field = extraction.get("invoice_date")
    date_prov = prov.get("invoice_date", {})

    # Filter to date-specific failure codes
    date_codes = [c for c in verifier_codes if c.startswith("DATE_")]

    result: dict[str, Any] = {
        "field_present": field is not None,
        "pass": len(date_codes) == 0 and field is not None,
        "failure_codes": date_codes,
    }

    if isinstance(field, dict):
        result["value"] = field.get("value")
        result["evidence"] = field.get("evidence")

    result["grounded"] = date_prov.get("grounded", False)
    result["normalized_value"] = date_prov.get("normalized_value")
    result["normalized_evidence"] = date_prov.get("normalized_evidence")
    result["match_tier"] = date_prov.get("match_tier", "not_found")

    return result


def extract_tax_diagnostic(
    extraction: dict, prov: dict, verifier_codes: list[str],
) -> dict:
    """Extract per-field diagnostic detail for tax_amount from provenance."""
    field = extraction.get("tax_amount")
    tax_prov = prov.get("tax_amount", {})

    # Filter to tax-specific failure codes
    tax_codes = [c for c in verifier_codes if c.startswith("TAX_")]

    result: dict[str, Any] = {
        "field_present": field is not None,
        "pass": len(tax_codes) == 0 and field is not None,
        "failure_codes": tax_codes,
    }

    if isinstance(field, dict):
        result["value"] = field.get("value")
        result["evidence"] = field.get("evidence")

    result["grounded"] = tax_prov.get("grounded", False)
    result["anchor_found"] = tax_prov.get("anchor_found")
    result["parsed_evidence"] = tax_prov.get("parsed_evidence")
    result["delta"] = tax_prov.get("delta")
    result["match_tier"] = tax_prov.get("match_tier", "not_found")

    return result


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def run_ff003_trace(records: list[dict]) -> list[dict]:
    """Run diagnostic trace for all 7 INV-107x records."""
    invoice_dir = gold_invoice_dir()
    results: list[dict] = []

    for rec in records:
        inv_id = rec["invoice_id"]
        if inv_id not in ALL_TRACE_IDS:
            continue

        raw_path = invoice_dir / rec["file"]
        raw_text = raw_path.read_text(encoding="utf-8")
        extraction = rec["mock_extraction"]

        # Full pipeline trace
        trace = trace_full_pipeline(raw_text, extraction)

        # Per-field diagnostics from verifier provenance
        prov = trace["verifier"]["provenance"]
        verifier_codes = trace["verifier"]["codes"]

        date_diag = extract_date_diagnostic(extraction, prov, verifier_codes)
        tax_diag = extract_tax_diagnostic(extraction, prov, verifier_codes)

        results.append({
            "invoice_id": inv_id,
            "is_ff003_target": inv_id in FF_003_IDS,
            "is_positive_control": inv_id == POSITIVE_CONTROL_ID,
            "tags": rec.get("tags", []),
            "expected_fields": rec.get("expected_fields", {}),
            "pipeline_trace": {
                "structural_pass": trace["structural"]["pass"],
                "semantic_pass": trace["semantic"]["pass"],
                "schema_pass": trace["schema"]["pass"],
                "verifier_pass": trace["verifier"]["pass"],
                "verifier_codes": verifier_codes,
                "arithmetic_pass": trace["arithmetic"]["pass"],
                "arithmetic_codes": trace["arithmetic"]["codes"],
                "arithmetic_check_ran": trace["arithmetic"]["check_ran"],
                "first_blocker": trace["first_blocker"],
                "would_pass_pipeline": trace["would_pass_pipeline"],
            },
            "date_diagnostic": date_diag,
            "tax_diagnostic": tax_diag,
        })

    # Sort: FF-003 targets first (by ID), then control
    results.sort(key=lambda r: (not r["is_ff003_target"], r["invoice_id"]))
    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _build_summary(results: list[dict], run_id: str) -> dict:
    """Build machine-readable summary from observed trace results."""
    ff003_results = [r for r in results if r["is_ff003_target"]]
    control_results = [r for r in results if r["is_positive_control"]]

    n_total = len(results)
    n_ff003 = len(ff003_results)

    # Per-field accuracy across all 7
    date_pass_count = sum(1 for r in results if r["date_diagnostic"]["pass"])
    tax_pass_count = sum(1 for r in results if r["tax_diagnostic"]["pass"])

    # First-blocker distribution across FF-003 targets
    blocker_dist = Counter(
        r["pipeline_trace"]["first_blocker"] for r in ff003_results
    )

    # Failure code distribution — date field
    date_code_dist: Counter[str] = Counter()
    for r in ff003_results:
        for code in r["date_diagnostic"]["failure_codes"]:
            date_code_dist[code] += 1

    # Failure code distribution — tax field
    tax_code_dist: Counter[str] = Counter()
    for r in ff003_results:
        for code in r["tax_diagnostic"]["failure_codes"]:
            tax_code_dist[code] += 1

    # Identify sub-patterns by grouping on dominant failure code
    sub_patterns: dict[str, list[str]] = {}
    for r in ff003_results:
        blocker = r["pipeline_trace"]["first_blocker"]
        if blocker == "verifier":
            # Use the first verifier code as the dominant code
            v_codes = r["pipeline_trace"]["verifier_codes"]
            dominant = v_codes[0] if v_codes else "UNKNOWN"
        elif blocker == "arithmetic":
            a_codes = r["pipeline_trace"]["arithmetic_codes"]
            dominant = a_codes[0] if a_codes else "ARITH_UNKNOWN"
        elif blocker is None:
            dominant = "PASS"
        else:
            dominant = blocker.upper()

        sub_patterns.setdefault(dominant, []).append(r["invoice_id"])

    # Control analysis
    ctrl = control_results[0] if control_results else None
    control_analysis = None
    if ctrl:
        control_analysis = {
            "invoice_id": ctrl["invoice_id"],
            "passes_pipeline": ctrl["pipeline_trace"]["would_pass_pipeline"],
            "date_pass": ctrl["date_diagnostic"]["pass"],
            "date_value": ctrl["date_diagnostic"].get("value"),
            "date_evidence": ctrl["date_diagnostic"].get("evidence"),
            "date_normalized": ctrl["date_diagnostic"].get("normalized_value"),
            "tax_pass": ctrl["tax_diagnostic"]["pass"],
            "tax_value": ctrl["tax_diagnostic"].get("value"),
            "tax_evidence": ctrl["tax_diagnostic"].get("evidence"),
            "tax_parsed": ctrl["tax_diagnostic"].get("parsed_evidence"),
            "arithmetic_pass": ctrl["pipeline_trace"]["arithmetic_pass"],
            "tags": ctrl["tags"],
        }

    # Reclassification candidates: cases that pass verifier but fail arithmetic
    reclass_candidates = [
        r["invoice_id"]
        for r in ff003_results
        if r["pipeline_trace"]["verifier_pass"]
        and not r["pipeline_trace"]["arithmetic_pass"]
    ]

    return {
        "analysis_id": run_id,
        "population": {
            "total_traced": n_total,
            "ff003_targets": n_ff003,
            "positive_controls": len(control_results),
        },
        "per_field_accuracy": {
            "invoice_date": {
                "pass_count": date_pass_count,
                "total": n_total,
                "accuracy": date_pass_count / n_total if n_total else 0,
            },
            "tax_amount": {
                "pass_count": tax_pass_count,
                "total": n_total,
                "accuracy": tax_pass_count / n_total if n_total else 0,
            },
        },
        "first_blocker_distribution": dict(blocker_dist),
        "date_failure_code_distribution": dict(date_code_dist),
        "tax_failure_code_distribution": dict(tax_code_dist),
        "sub_patterns": sub_patterns,
        "reclassification_candidates": {
            "ids": reclass_candidates,
            "note": (
                "These cases pass the verifier but fail arithmetic "
                "(ARITH_TOTAL_MISMATCH). They may overlap with FF-001/L1 "
                "rather than belonging to FF-003/L3."
            ) if reclass_candidates else "No reclassification candidates identified.",
        },
        "control_analysis": control_analysis,
        "per_case_traces": [
            {
                "invoice_id": r["invoice_id"],
                "is_ff003_target": r["is_ff003_target"],
                "is_positive_control": r["is_positive_control"],
                "tags": r["tags"],
                "structural_pass": r["pipeline_trace"]["structural_pass"],
                "semantic_pass": r["pipeline_trace"]["semantic_pass"],
                "schema_pass": r["pipeline_trace"]["schema_pass"],
                "verifier_pass": r["pipeline_trace"]["verifier_pass"],
                "verifier_codes": r["pipeline_trace"]["verifier_codes"],
                "arithmetic_pass": r["pipeline_trace"]["arithmetic_pass"],
                "arithmetic_codes": r["pipeline_trace"]["arithmetic_codes"],
                "first_blocker": r["pipeline_trace"]["first_blocker"],
                "would_pass_pipeline": r["pipeline_trace"]["would_pass_pipeline"],
                "date_pass": r["date_diagnostic"]["pass"],
                "date_codes": r["date_diagnostic"]["failure_codes"],
                "date_value": r["date_diagnostic"].get("value"),
                "date_evidence": r["date_diagnostic"].get("evidence"),
                "date_normalized_value": r["date_diagnostic"].get("normalized_value"),
                "date_normalized_evidence": r["date_diagnostic"].get("normalized_evidence"),
                "date_match_tier": r["date_diagnostic"].get("match_tier"),
                "tax_pass": r["tax_diagnostic"]["pass"],
                "tax_codes": r["tax_diagnostic"]["failure_codes"],
                "tax_value": r["tax_diagnostic"].get("value"),
                "tax_evidence": r["tax_diagnostic"].get("evidence"),
                "tax_anchor_found": r["tax_diagnostic"].get("anchor_found"),
                "tax_parsed_evidence": r["tax_diagnostic"].get("parsed_evidence"),
                "tax_delta": r["tax_diagnostic"].get("delta"),
                "tax_match_tier": r["tax_diagnostic"].get("match_tier"),
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# FINDINGS.md
# ---------------------------------------------------------------------------


def _build_findings_md(summary: dict, results: list[dict]) -> str:
    """Build human-readable FINDINGS.md from observed trace results."""
    lines: list[str] = []

    lines.append("# FF-003 Extended-Field Analysis — Findings")
    lines.append("")

    # Purpose
    lines.append("## Purpose")
    lines.append("")
    lines.append(
        "Identify the specific failure code(s) blocking each of the 6 FF-003 cases "
        "(INV-1070 through INV-1075), and explain why INV-1076 passes. All 7 records "
        "include `invoice_date` and `tax_amount` in expected_fields. The taxonomy "
        "currently classifies FF-003 as L3 (evidence-binding) with hypothesized failure "
        "codes. This analysis confirms or refutes those hypotheses."
    )
    lines.append("")

    # Method
    lines.append("## Method")
    lines.append("")
    lines.append("1. For each of the 7 INV-107x records, run all 5 validation steps individually")
    lines.append("2. Extract per-field diagnostic detail from verifier provenance (invoice_date, tax_amount)")
    lines.append("3. Identify the first blocker in pipeline order for each case")
    lines.append("4. Group cases by dominant failure code to identify sub-patterns")
    lines.append("5. Compare failing cases against INV-1076 (the positive control)")
    lines.append("")

    # Results table
    lines.append("## Results")
    lines.append("")
    lines.append(
        "| Invoice | Role | Date | Date Code | Tax | Tax Code | Arith | First Blocker |"
    )
    lines.append(
        "|---------|------|------|-----------|-----|----------|-------|---------------|"
    )
    for r in results:
        inv_id = r["invoice_id"]
        role = "Control" if r["is_positive_control"] else "FF-003"

        date_pass = "PASS" if r["date_diagnostic"]["pass"] else "FAIL"
        date_codes = r["date_diagnostic"]["failure_codes"]
        date_code_str = date_codes[0] if date_codes else "—"

        tax_pass = "PASS" if r["tax_diagnostic"]["pass"] else "FAIL"
        tax_codes = r["tax_diagnostic"]["failure_codes"]
        tax_code_str = tax_codes[0] if tax_codes else "—"

        arith_pass = "PASS" if r["pipeline_trace"]["arithmetic_pass"] else "FAIL"
        if not r["pipeline_trace"]["arithmetic_check_ran"]:
            arith_pass = "N/A"

        blocker = r["pipeline_trace"]["first_blocker"] or "none"

        lines.append(
            f"| {inv_id} | {role} | {date_pass} | {date_code_str} "
            f"| {tax_pass} | {tax_code_str} | {arith_pass} | {blocker} |"
        )
    lines.append("")

    # Per-field accuracy
    pf = summary["per_field_accuracy"]
    lines.append("## Per-field accuracy (across all 7 records)")
    lines.append("")
    lines.append(
        f"- **invoice_date**: {pf['invoice_date']['pass_count']}/{pf['invoice_date']['total']} "
        f"pass ({pf['invoice_date']['accuracy']:.1%})"
    )
    lines.append(
        f"- **tax_amount**: {pf['tax_amount']['pass_count']}/{pf['tax_amount']['total']} "
        f"pass ({pf['tax_amount']['accuracy']:.1%})"
    )
    lines.append("")

    # Sub-patterns
    lines.append("## Observed sub-patterns")
    lines.append("")
    for code, ids in sorted(summary["sub_patterns"].items()):
        lines.append(f"### {code} ({len(ids)} case{'s' if len(ids) != 1 else ''})")
        lines.append("")
        lines.append(f"Cases: {', '.join(ids)}")
        lines.append("")

        # Per-code analysis with observed evidence
        matching = [r for r in results if r["invoice_id"] in ids]
        if code == "DATE_AMBIGUOUS":
            lines.append(
                "The verifier's date parser (`_parse_date_token`) cannot disambiguate "
                "slash-delimited dates where both components are ≤ 12 (e.g., MM/DD vs DD/MM). "
                "Observed date evidence for these cases:"
            )
            lines.append("")
            for r in matching:
                ev = r["date_diagnostic"].get("evidence", "?")
                val = r["date_diagnostic"].get("value", "?")
                lines.append(f"- **{r['invoice_id']}**: value=`{val}`, evidence=`{ev}`")
            lines.append("")
        elif code == "TAX_AMOUNT_MISMATCH":
            lines.append(
                "The verifier's tax parser (`_TAX_ANCHOR_VALUE_RE`) captures the first "
                "number after a tax/vat/gst anchor within 24 non-digit characters. When "
                "the evidence contains an embedded percentage (e.g., \"VAT (19%)\"), the "
                "regex captures the percentage rather than the actual tax amount. "
                "Observed tax evidence for these cases:"
            )
            lines.append("")
            for r in matching:
                ev = r["tax_diagnostic"].get("evidence", "?")
                val = r["tax_diagnostic"].get("value", "?")
                parsed = r["tax_diagnostic"].get("parsed_evidence", "?")
                delta = r["tax_diagnostic"].get("delta", "?")
                lines.append(
                    f"- **{r['invoice_id']}**: value=`{val}`, evidence=`{ev}`, "
                    f"parsed=`{parsed}`, delta=`{delta}`"
                )
            lines.append("")
        elif code == "ARITH_TOTAL_MISMATCH":
            lines.append(
                "These cases pass the verifier (all field-level checks succeed) but "
                "fail the arithmetic check (`check_arithmetic`). The raw invoice text "
                "contains line items that do not sum to the stated total."
            )
            lines.append("")
            for r in matching:
                a_codes = r["pipeline_trace"]["arithmetic_codes"]
                lines.append(
                    f"- **{r['invoice_id']}**: verifier=PASS, arithmetic codes={a_codes}"
                )
            lines.append("")
            lines.append(
                "> **Reclassification note**: These cases pass the L3 evidence-binding "
                "verifier. Their blocker is L1 input-text arithmetic, which overlaps with "
                "FF-001. Consider whether they should remain in FF-003 or be reclassified."
            )
            lines.append("")
        else:
            for r in matching:
                v_codes = r["pipeline_trace"]["verifier_codes"]
                lines.append(f"- **{r['invoice_id']}**: verifier_codes={v_codes}")
            lines.append("")

    # Control analysis
    ctrl = summary.get("control_analysis")
    if ctrl:
        lines.append("## Control case: INV-1076")
        lines.append("")
        lines.append(f"- **Passes full pipeline**: {ctrl['passes_pipeline']}")
        lines.append(f"- **Date**: pass={ctrl['date_pass']}, "
                      f"value=`{ctrl['date_value']}`, evidence=`{ctrl['date_evidence']}`, "
                      f"normalized=`{ctrl['date_normalized']}`")
        lines.append(f"- **Tax**: pass={ctrl['tax_pass']}, "
                      f"value=`{ctrl['tax_value']}`, evidence=`{ctrl['tax_evidence']}`, "
                      f"parsed=`{ctrl['tax_parsed']}`")
        lines.append(f"- **Arithmetic**: pass={ctrl['arithmetic_pass']}")
        lines.append(f"- **Tags**: {ctrl['tags']}")
        lines.append("")
        lines.append(
            "INV-1076 is the only INV-107x record that passes all validation gates. "
            "Comparing its field values against the failing cases reveals what "
            "differentiates it."
        )
        lines.append("")

    # Reclassification candidates
    reclass = summary["reclassification_candidates"]
    if reclass["ids"]:
        lines.append("## Reclassification candidates")
        lines.append("")
        lines.append(f"Cases: {', '.join(reclass['ids'])}")
        lines.append("")
        lines.append(reclass["note"])
        lines.append("")

    # First-blocker distribution
    lines.append("## First-blocker distribution (FF-003 targets only)")
    lines.append("")
    for blocker, count in sorted(summary["first_blocker_distribution"].items()):
        lines.append(f"- **{blocker}**: {count}")
    lines.append("")

    # Recommended next actions
    lines.append("## Recommended next actions")
    lines.append("")
    lines.append(
        "These are descriptive recommendations based on the observed failure modes. "
        "No rescue implementation or production code changes are proposed."
    )
    lines.append("")

    sub = summary["sub_patterns"]
    if "DATE_AMBIGUOUS" in sub:
        lines.append(
            f"1. **DATE_AMBIGUOUS** ({len(sub['DATE_AMBIGUOUS'])} cases): "
            "Consider a date disambiguation strategy — e.g., require ISO format "
            "in extraction prompts, or use document-level locale hints to resolve "
            "MM/DD vs DD/MM ambiguity."
        )
    if "TAX_AMOUNT_MISMATCH" in sub:
        lines.append(
            f"2. **TAX_AMOUNT_MISMATCH** ({len(sub['TAX_AMOUNT_MISMATCH'])} cases): "
            "The `_TAX_ANCHOR_VALUE_RE` regex captures the first number after the "
            "anchor keyword. When the evidence contains an embedded percentage, this "
            "is the percentage rather than the tax amount. A regex improvement or "
            "extraction prompt change could address this."
        )
    if "ARITH_TOTAL_MISMATCH" in sub:
        lines.append(
            f"3. **ARITH_TOTAL_MISMATCH** ({len(sub['ARITH_TOTAL_MISMATCH'])} cases): "
            "These cases pass the verifier but fail arithmetic. Assess whether they "
            "should be reclassified to FF-001/L1 (input-text arithmetic corruption)."
        )
    lines.append(
        "4. **Dataset expansion**: The current FF-003 population (7 records) is too "
        "small for reliable rescue policy design. Expand the gold dataset with more "
        "`invoice_date` + `tax_amount` test cases before designing any intervention."
    )
    lines.append("")

    # Limitations
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- This trace runs validators in isolation, not through the full graph. "
        "Graph-level routing behavior is inferred, not directly observed."
    )
    lines.append(
        "- N=7 (6 targets + 1 control) — small sample, interpret cautiously."
    )
    lines.append(
        "- All records use mock_extractions. Real LLM extraction may produce "
        "different evidence strings and different failure profiles."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _export_results(summary: dict, findings_md: str, output_dir: Path) -> None:
    """Write analysis.json and FINDINGS.md to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "analysis.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    with (output_dir / "FINDINGS.md").open("w", encoding="utf-8") as f:
        f.write(findings_md)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_ff003_analysis() -> dict:
    """Run the FF-003 extended-field analysis and export findings."""
    run_id = "ff003_analysis_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    records = load_expected_records()
    results = run_ff003_trace(records)

    summary = _build_summary(results, run_id)
    findings_md = _build_findings_md(summary, results)

    output_dir = Path(__file__).resolve().parent / "artifacts" / "FF_003_ANALYSIS"
    _export_results(summary, findings_md, output_dir)

    # Console output
    print(f"Analysis ID: {run_id}")
    print(f"Population: {summary['population']}")
    pf = summary["per_field_accuracy"]
    print(f"invoice_date accuracy: {pf['invoice_date']['pass_count']}/{pf['invoice_date']['total']}"
          f" ({pf['invoice_date']['accuracy']:.1%})")
    print(f"tax_amount accuracy: {pf['tax_amount']['pass_count']}/{pf['tax_amount']['total']}"
          f" ({pf['tax_amount']['accuracy']:.1%})")
    print(f"First-blocker distribution: {summary['first_blocker_distribution']}")
    print(f"Sub-patterns: { {k: len(v) for k, v in summary['sub_patterns'].items()} }")
    if summary["reclassification_candidates"]["ids"]:
        print(f"Reclassification candidates: {summary['reclassification_candidates']['ids']}")
    if summary["control_analysis"]:
        ctrl = summary["control_analysis"]
        print(f"Control ({ctrl['invoice_id']}): pipeline={'PASS' if ctrl['passes_pipeline'] else 'FAIL'}")
    print(f"\nArtifacts written to: {output_dir}")

    return summary


if __name__ == "__main__":
    run_ff003_analysis()
