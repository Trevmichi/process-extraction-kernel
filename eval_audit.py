"""
eval_audit.py
Optional LLM-based auditing layer for the AP extraction eval harness.

Advisory only — never affects scoring, routing, or pass/fail decisions.
Explains failures, probes passing invoices for "accidental correctness",
and optionally suggests new test cases.

Usage (from eval_runner.py):
    python eval_runner.py --audit --audit-sample 5
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.verifier import MONEY_RE, CURRENCY_RE, PO_RE, normalize_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERDICTS = ("dataset_issue", "deterministic_bug", "model_extraction_error",
            "suspicious_pass", "unclear")

ROOT_CAUSE_CATEGORIES = ("AMOUNT_DISAMBIGUATION", "PO_DETECTION",
                         "VENDOR_GARBAGE", "ROUTING_AMBIGUITY",
                         "EVIDENCE_GROUNDING", "DATASET_LABEL", "OTHER")

_TOTAL_KEYWORDS = ("total", "amount due", "balance due", "sum")


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------
def select_audit_targets(
    results: list[dict],
    audit_mode: str,
    audit_sample: int,
    audit_seed: int,
    audit_max: int | None = None,
) -> list[dict]:
    """Select invoices to audit based on mode and sample size.

    Returns a stable-ordered subset of per-invoice result dicts.
    """
    failures = [r for r in results if r.get("failure_bucket") != "pass"]
    passes = [r for r in results if r.get("failure_bucket") == "pass"]

    rng = random.Random(audit_seed)
    sample_count = min(audit_sample, len(passes))
    sampled_passes = rng.sample(passes, sample_count) if sample_count > 0 else []

    if audit_mode == "failures_only":
        targets = list(failures)
    elif audit_mode == "sample_only":
        targets = list(sampled_passes)
    else:  # failures_and_sample
        targets = list(failures) + sampled_passes

    # Apply audit_max cap (trim from sampled passes first)
    if audit_max is not None and len(targets) > audit_max:
        failure_ids = {r["invoice_id"] for r in failures}
        kept_failures = [t for t in targets if t["invoice_id"] in failure_ids]
        kept_passes = [t for t in targets if t["invoice_id"] not in failure_ids]
        remaining = audit_max - len(kept_failures)
        if remaining < 0:
            kept_failures = kept_failures[:audit_max]
            kept_passes = []
        else:
            kept_passes = kept_passes[:remaining]
        targets = kept_failures + kept_passes

    # Stable ordering
    targets.sort(key=lambda r: r["invoice_id"])
    return targets


# ---------------------------------------------------------------------------
# Diagnostic snapshot (D1 — harness-side)
# ---------------------------------------------------------------------------
def build_diagnostic_snapshot(
    raw_text: str, gold_record: dict, result: dict,
) -> dict:
    """Build a harness-side diagnostic snapshot for audit consumption."""
    norm = normalize_text(raw_text)

    # Amount candidates
    cleaned = CURRENCY_RE.sub("", norm)
    amount_candidates = []
    for m in MONEY_RE.finditer(cleaned):
        raw_num = m.group().replace(",", "")
        if not raw_num or raw_num == ".":
            continue
        try:
            amount_candidates.append(float(raw_num))
        except ValueError:
            continue

    # Total line candidates
    total_line_candidates = []
    for line in raw_text.splitlines():
        lower = line.lower().strip()
        if any(kw in lower for kw in _TOTAL_KEYWORDS) and lower:
            total_line_candidates.append(line.strip())

    # PO candidates
    po_candidates = [m.group() for m in PO_RE.finditer(raw_text)]

    # Vendor line candidates (first 5 non-empty lines)
    vendor_line_candidates = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped:
            vendor_line_candidates.append(stripped)
            if len(vendor_line_candidates) >= 5:
                break

    # Trace summary from audit_log
    trace_summary = _parse_trace_summary(result.get("audit_log", []))

    return {
        "amount_candidates": amount_candidates,
        "total_line_candidates": total_line_candidates,
        "po_candidates": po_candidates,
        "vendor_line_candidates": vendor_line_candidates,
        "trace_summary": trace_summary,
    }


def _parse_trace_summary(audit_log: list) -> dict:
    """Extract structured trace summary from audit_log entries."""
    route_decisions = []
    terminal_status = None
    exception_station = None
    verifier_summary = None
    amount_candidates_event = None

    for entry in audit_log:
        try:
            obj = json.loads(entry)
        except (json.JSONDecodeError, TypeError):
            continue

        event = obj.get("event")
        if event == "route_decision":
            route_decisions.append({
                "from_node": obj.get("from_node"),
                "selected": obj.get("selected"),
                "reason": obj.get("reason"),
            })
        elif event == "exception_station":
            exception_station = obj.get("reason")
        elif event == "verifier_summary":
            verifier_summary = obj
        elif event == "amount_candidates":
            amount_candidates_event = obj.get("candidates", [])

    return {
        "route_decisions": route_decisions,
        "terminal_status": terminal_status,
        "exception_station": exception_station,
        "verifier_summary": verifier_summary,
        "amount_candidates_event": amount_candidates_event,
    }


# ---------------------------------------------------------------------------
# Signals detection (deterministic)
# ---------------------------------------------------------------------------
def compute_signals(snapshot: dict, gold_record: dict) -> dict:
    """Compute deterministic signal flags from snapshot + gold record."""
    return {
        "multiple_total_candidates": len(snapshot["amount_candidates"]) > 1,
        "po_missing_but_has_po_true": (
            gold_record.get("expected_fields", {}).get("has_po", False)
            and len(snapshot["po_candidates"]) == 0
        ),
    }


# ---------------------------------------------------------------------------
# Audit packet construction
# ---------------------------------------------------------------------------
def build_audit_packet(
    result: dict,
    gold_record: dict,
    raw_text: str,
    snapshot: dict,
) -> dict:
    """Build the full context dict for the audit LLM prompt."""
    return {
        "invoice_id": result["invoice_id"],
        "file": gold_record.get("file", ""),
        "raw_invoice_text": raw_text,
        "expected": {
            "status": gold_record.get("expected_status", []),
            "fields": gold_record.get("expected_fields", {}),
        },
        "actual": {
            "status": result.get("actual_status", ""),
            "fields": {
                f: comp.get("actual")
                for f, comp in result.get("field_comparison", {}).items()
            },
        },
        "deterministic_diffs": {
            "failure_bucket": result.get("failure_bucket", ""),
            "field_mismatches": result.get("field_mismatches", []),
            "status_expected": gold_record.get("expected_status", []),
            "status_actual": result.get("actual_status", ""),
        },
        "diagnostic_snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# Audit LLM prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are an auditing model for an AP invoice extraction pipeline.
You will receive a JSON packet containing:
- raw invoice text
- expected fields/status (gold standard)
- actual extracted fields/status (from deterministic pipeline)
- diagnostic snapshot (amount candidates, PO candidates, routing trace, verifier results)

Your task: diagnose WHY the deterministic result differs from expected (for failures)
or whether the pass is genuinely correct (for passes).

OUTPUT: Respond with a single JSON object. No markdown, no commentary, no text outside the JSON.

Required JSON schema:
{
  "verdict": "<one of: dataset_issue, deterministic_bug, model_extraction_error, suspicious_pass, unclear>",
  "confidence": <float 0.0-1.0>,
  "root_cause_category": "<one of: AMOUNT_DISAMBIGUATION, PO_DETECTION, VENDOR_GARBAGE, ROUTING_AMBIGUITY, EVIDENCE_GROUNDING, DATASET_LABEL, OTHER>",
  "explanation": "<string — cite exact substrings from the invoice text when making claims>",
  "recommended_action": "<string — what should be fixed>",
  "suggested_new_test_cases": [
    {
      "title": "<string>",
      "why": "<string>",
      "minimal_invoice_pattern": "<string>",
      "tags": ["<string>"]
    }
  ]
}

Verdict definitions:
- dataset_issue: Gold record is inconsistent (wrong expected_status, missing PO: None, evidence mismatch)
- deterministic_bug: Router/condition/verifier logic is wrong — the pipeline misbehaved
- model_extraction_error: The LLM extraction node produced wrong output; pipeline behaved correctly given bad input
- suspicious_pass: Passed, but evidence is weak — multiple plausible totals, vendor ambiguity, or amount matched by coincidence rather than deterministic disambiguation
- unclear: Cannot determine root cause with available information

Rules:
- ALWAYS quote exact strings from the invoice text when making claims
- suggested_new_test_cases: 0-3 entries. Leave empty [] if no gaps detected
- confidence: 0.0 = pure guess, 1.0 = certain
"""


def _build_user_prompt(packet: dict) -> str:
    """Build the user prompt from an audit packet."""
    return json.dumps(packet, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------
def _extract_json(raw: str) -> dict:
    """Extract JSON from potentially messy LLM output.

    Strips markdown fences, finds first { and last }, then parses.
    """
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

    # Find JSON boundaries
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return json.loads(text)


def audit_llm_call(
    prompt: str,
    provider: str,
    model: str | None,
    timeout_secs: int,
) -> dict:
    """Call LLM provider for audit. Returns parsed dict or {"_error": str}."""
    start = time.time()
    try:
        if provider == "ollama":
            return _call_ollama(prompt, model or "gemma3:12b", timeout_secs)
        elif provider == "openai":
            return _call_openai(prompt, model or "gpt-4o-mini", timeout_secs)
        else:
            return {"_error": f"Unknown provider: {provider}"}
    except Exception as exc:
        return {"_error": str(exc)}
    finally:
        elapsed = time.time() - start
        if elapsed > 20:
            print(f"  [audit] WARNING: LLM call took {elapsed:.1f}s",
                  file=sys.stderr)


def _call_ollama(prompt: str, model: str, timeout_secs: int) -> dict:
    """Call Ollama via langchain_ollama (preferred) or raw HTTP fallback."""
    try:
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOllama(
            model=model,
            temperature=0.0,
            format="json",
            timeout=timeout_secs,
        )
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return _extract_json(response.content)
    except ImportError:
        # Fallback: direct HTTP to Ollama API (no langchain dependency)
        import urllib.request
        import urllib.error

        url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_secs) as resp:
            body = json.loads(resp.read())
        raw = body.get("message", {}).get("content", "")
        return _extract_json(raw)


def _call_openai(prompt: str, model: str, timeout_secs: int) -> dict:
    """Call OpenAI API with JSON mode."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"_error": "OPENAI_API_KEY not set"}

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=timeout_secs)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    raw = response.choices[0].message.content or ""
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Audit result validation
# ---------------------------------------------------------------------------
def _validate_audit_result(raw: dict) -> dict:
    """Validate and normalize an audit LLM response.

    Returns a well-formed llm_audit dict even if the LLM produced garbage.
    """
    verdict = raw.get("verdict", "unclear")
    if verdict not in VERDICTS:
        verdict = "unclear"

    root_cause = raw.get("root_cause_category", "OTHER")
    if root_cause not in ROOT_CAUSE_CATEGORIES:
        root_cause = "OTHER"

    confidence = raw.get("confidence", 0.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    suggested = raw.get("suggested_new_test_cases", [])
    if not isinstance(suggested, list):
        suggested = []
    # Cap at 3
    suggested = suggested[:3]

    return {
        "verdict": verdict,
        "confidence": confidence,
        "root_cause_category": root_cause,
        "explanation": str(raw.get("explanation", "")),
        "recommended_action": str(raw.get("recommended_action", "")),
        "suggested_new_test_cases": suggested,
    }


def _make_unclear_result(reason: str) -> dict:
    """Create an 'unclear' audit result for LLM failures."""
    return {
        "verdict": "unclear",
        "confidence": 0.0,
        "root_cause_category": "OTHER",
        "explanation": reason,
        "recommended_action": "",
        "suggested_new_test_cases": [],
    }


# ---------------------------------------------------------------------------
# Main audit runner
# ---------------------------------------------------------------------------
def run_audit(
    results: list[dict],
    gold_records: list[dict],
    datasets_dir: Path,
    audit_mode: str = "failures_and_sample",
    audit_sample: int = 5,
    audit_seed: int = 1337,
    audit_max: int | None = None,
    provider: str = "ollama",
    model: str | None = None,
    timeout_secs: int = 30,
) -> dict:
    """Run the LLM audit layer on selected invoices.

    Returns the full audit report dict ready for JSON serialization.
    """
    # Build gold record lookup
    gold_lookup = {r["invoice_id"]: r for r in gold_records}

    # Select targets
    targets = select_audit_targets(
        results, audit_mode, audit_sample, audit_seed, audit_max,
    )

    effective_model = model or ("gemma3:12b" if provider == "ollama" else "gpt-4o-mini")

    print(f"[audit] Auditing {len(targets)} invoices "
          f"(provider={provider}, model={effective_model})")

    audits = []
    for i, result in enumerate(targets, 1):
        inv_id = result["invoice_id"]
        gold = gold_lookup.get(inv_id, {})
        file_name = gold.get("file", "")

        # Load raw text
        try:
            text_path = datasets_dir / "gold_invoices" / file_name
            raw_text = text_path.read_text(encoding="utf-8")
        except Exception:
            raw_text = ""

        # Build snapshot and packet
        snapshot = build_diagnostic_snapshot(raw_text, gold, result)
        signals = compute_signals(snapshot, gold)
        packet = build_audit_packet(result, gold, raw_text, snapshot)

        # Call LLM
        print(f"  [{i}/{len(targets)}] {inv_id} ...", end=" ", flush=True)
        user_prompt = _build_user_prompt(packet)
        llm_raw = audit_llm_call(user_prompt, provider, model, timeout_secs)

        if "_error" in llm_raw:
            llm_audit = _make_unclear_result(
                f"LLM call failed: {llm_raw['_error']}"
            )
            print("ERROR")
        else:
            llm_audit = _validate_audit_result(llm_raw)
            print(llm_audit["verdict"])

        audits.append({
            "invoice_id": inv_id,
            "failure_bucket": result.get("failure_bucket", ""),
            "deterministic": {
                "status_expected": gold.get("expected_status", []),
                "status_actual": result.get("actual_status", ""),
                "field_mismatches": result.get("field_mismatches", []),
            },
            "llm_audit": llm_audit,
            "signals": signals,
        })

    # Build summary
    failures_audited = sum(
        1 for a in audits if a["failure_bucket"] != "pass"
    )
    passes_audited = sum(
        1 for a in audits if a["failure_bucket"] == "pass"
    )
    any_suspicious = any(
        a["llm_audit"]["verdict"] == "suspicious_pass" for a in audits
    )

    return {
        "run": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "audit_mode": audit_mode,
            "audit_sample": audit_sample,
            "audit_seed": audit_seed,
            "provider": provider,
            "model": effective_model,
        },
        "summary": {
            "audited_count": len(audits),
            "failures_audited": failures_audited,
            "passes_audited": passes_audited,
            "flags": {
                "any_high_risk_passes": any_suspicious,
            },
        },
        "audits": audits,
    }


# ---------------------------------------------------------------------------
# Markdown audit report
# ---------------------------------------------------------------------------
def write_audit_md_report(
    audit_metrics: dict, outpath: str | Path,
) -> None:
    """Write a Markdown audit summary report."""
    lines: list[str] = []
    lines.append("# Audit Report\n")

    # Summary
    summary = audit_metrics.get("summary", {})
    run_info = audit_metrics.get("run", {})
    lines.append(f"**Provider**: {run_info.get('provider', '?')} "
                 f"({run_info.get('model', '?')})")
    lines.append(f"**Mode**: {run_info.get('audit_mode', '?')} "
                 f"(sample={run_info.get('audit_sample', '?')}, "
                 f"seed={run_info.get('audit_seed', '?')})")
    lines.append(f"**Audited**: {summary.get('audited_count', 0)} invoices "
                 f"({summary.get('failures_audited', 0)} failures, "
                 f"{summary.get('passes_audited', 0)} passes)")
    if summary.get("flags", {}).get("any_high_risk_passes"):
        lines.append("\n**WARNING**: Suspicious passes detected!\n")
    lines.append("")

    # Per-invoice table
    audits = audit_metrics.get("audits", [])
    if audits:
        lines.append("## Per-Invoice Audit\n")
        lines.append("| Invoice | Verdict | Root Cause | Bucket | Confidence |")
        lines.append("|---------|---------|------------|--------|------------|")
        for a in audits:
            la = a.get("llm_audit", {})
            lines.append(
                f"| {a['invoice_id']} "
                f"| {la.get('verdict', '?')} "
                f"| {la.get('root_cause_category', '?')} "
                f"| {a.get('failure_bucket', '?')} "
                f"| {la.get('confidence', 0):.0%} |"
            )
        lines.append("")

    # Top themes
    themes: dict[str, list[str]] = defaultdict(list)
    for a in audits:
        cat = a.get("llm_audit", {}).get("root_cause_category", "OTHER")
        themes[cat].append(a["invoice_id"])

    if themes:
        lines.append("## Top Themes\n")
        lines.append("| Root Cause | Count | Invoices |")
        lines.append("|------------|-------|----------|")
        for cat in sorted(themes.keys()):
            ids = themes[cat]
            lines.append(f"| {cat} | {len(ids)} | {', '.join(ids)} |")
        lines.append("")

    # Suspicious passes
    suspicious = [a for a in audits
                  if a.get("llm_audit", {}).get("verdict") == "suspicious_pass"]
    if suspicious:
        lines.append("## Suspicious Passes\n")
        for a in suspicious:
            la = a["llm_audit"]
            lines.append(f"### {a['invoice_id']}\n")
            lines.append(f"**Explanation**: {la.get('explanation', '')}\n")
            lines.append(f"**Recommended**: {la.get('recommended_action', '')}\n")

    Path(outpath).write_text("\n".join(lines), encoding="utf-8")
