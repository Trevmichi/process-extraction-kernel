"""
eval_variance.py
Variance (fragility) testing for the AP extraction pipeline.

Measures LLM extraction non-determinism by invoking the extraction prompt
multiple times for the same invoice and computing a fragility score.

This is inherently a live-LLM feature.  In tests the LLM call is mocked
via ``_call_llm_json``.
"""
from __future__ import annotations

from src.agent.nodes import _call_llm_json, build_enter_record_prompt
from eval_runner import compare_fields

# Fields tracked for variance
_EXTRACTION_FIELDS = ("vendor", "amount", "has_po")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_extraction(parsed: dict) -> dict:
    """Flatten nested extraction dict to ``{field: value}`` for compare_fields.

    Input:  ``{"vendor": {"value": "X", "evidence": "..."}, ...}``
    Output: ``{"vendor": "X", "amount": 500.0, "has_po": True}``

    Missing or malformed fields map to ``None``.
    """
    flat: dict = {}
    for field in _EXTRACTION_FIELDS:
        entry = parsed.get(field)
        if isinstance(entry, dict):
            flat[field] = entry.get("value")
        else:
            flat[field] = None
    return flat


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run_variance_test(
    invoice_id: str,
    raw_text: str,
    gold_record: dict,
    runs: int = 5,
) -> dict:
    """Run the extraction prompt *runs* times and measure consistency.

    Parameters
    ----------
    invoice_id : Unique invoice identifier (for labeling).
    raw_text : The invoice text to extract from.
    gold_record : Gold record dict with ``expected_fields`` key.
    runs : Number of LLM invocations.

    Returns
    -------
    dict with keys: ``invoice_id``, ``runs``, ``matches``,
    ``fragility_score``, ``unstable_fields``, ``per_run``.
    """
    expected_fields = gold_record["expected_fields"]
    prompt = build_enter_record_prompt(raw_text)

    per_run: list[dict] = []
    match_count = 0
    field_match_counts: dict[str, int] = {f: 0 for f in expected_fields}

    for i in range(runs):
        parsed = _call_llm_json(prompt)

        if "_error" in parsed:
            comparison = {
                f: {"expected": expected_fields[f], "actual": None, "match": False}
                for f in expected_fields
            }
            all_match = False
        else:
            flat = _flatten_extraction(parsed)
            comparison = compare_fields(expected_fields, flat)
            all_match = all(c["match"] for c in comparison.values())

        if all_match:
            match_count += 1

        for f in expected_fields:
            if comparison.get(f, {}).get("match", False):
                field_match_counts[f] += 1

        per_run.append({
            "run": i + 1,
            "all_match": all_match,
            "comparison": comparison,
        })

    unstable_fields = [
        f for f, count in field_match_counts.items()
        if count < runs
    ]

    return {
        "invoice_id": invoice_id,
        "runs": runs,
        "matches": match_count,
        "fragility_score": match_count / runs if runs > 0 else 0.0,
        "unstable_fields": unstable_fields,
        "per_run": per_run,
    }
