from __future__ import annotations
import re
from typing import Dict, List

def _clean(s: str) -> str:
    s = (s or "").strip()
    # normalize whitespace and punctuation spacing
    s = re.sub(r"\s+", " ", s)
    s = s.replace("’", "'")
    # Fix common mojibake + normalize dashes
    s = s.replace("â€”", "—").replace("â€“", "–").replace("Â", "")
    return s

def _canon_question(q: str) -> str:
    q = _clean(q)

    # --- Canonical rewrite rules (domain-specific AP) ---
    # 3-way match success path
    if re.search(r"invoice matches the PO and goods receipt", q, re.I):
        return "If the invoice matches the PO and goods receipt (match), what are the explicit outcomes and next steps?"

    # 3-way match fail path
    if re.search(r"(3-way match.*fails|invoice does not match|does NOT match|no_match)", q, re.I):
        return "If 3-way match fails (no_match), what is the process (hold, vendor contact, reject, override)?"

    # Threshold approval rule
    if re.search(r"(over\s*\$?\s*5,?000|above\s*\$?\s*5,?000|director approval)", q, re.I):
        return "Invoices over $5,000 require director approval — what are the explicit outcomes and next steps?"

    # Match tolerance rule
    if re.search(r"(match tolerance|tolerances|price/quantity variances)", q, re.I):
        return "What is the match tolerance for price/quantity variances in matching (and who sets it)?"

    return q

def _unknown_key(q_canon: str) -> str:
    q = (q_canon or "").lower()
    if "3-way match fails" in q or "no_match" in q:
        return "U.NO_MATCH_PATH"
    if "match tolerance" in q or "price/quantity variances" in q:
        return "U.MATCH_TOLERANCE"
    if "invoices over $5,000" in q or "director approval" in q:
        return "U.THRESHOLD_BRANCHES"
    if "invoice matches the po and goods receipt" in q and "(match)" in q:
        return "U.MATCH_BRANCHES"
    return "U.OTHER"

def normalize_unknowns(proc) -> List[Dict]:
    """
    Normalizes unknown question phrasing and removes duplicates by canonical question.
    Adds:
      - question: canonicalized question
      - key: stable key derived from canonical question
      - meta.original_question: preserves the original
    Returns a small report list for optional tracing.
    """
    if not getattr(proc, "unknowns", None):
        return []

    report: List[Dict] = []
    seen: Dict[str, Dict] = {}
    new_unknowns: List[Dict] = []

    for u in (proc.unknowns or []):
        q0 = u.get("question", "") or ""
        q_clean = _canon_question(q0)

        # preserve original if changed
        if q_clean != _clean(q0):
            meta = u.get("meta") or {}
            meta.setdefault("original_question", q0)
            u["meta"] = meta

        u["question"] = q_clean
        u["key"] = _unknown_key(q_clean)

        # de-dupe by canonical question
        if q_clean in seen:
            report.append({"type": "dedupe", "question": q_clean})
            continue

        seen[q_clean] = u
        new_unknowns.append(u)

    proc.unknowns = new_unknowns
    return report
