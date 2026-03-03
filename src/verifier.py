"""
verifier.py
Deterministic evidence-based extraction verifier.

``verify_extraction(raw_text, extraction)`` cross-checks that the LLM's
claimed evidence actually appears in the source text and that derived
values are consistent with that evidence.

All failure reasons are stable ``FailureCode`` literals — never freeform
strings — so downstream consumers can switch on them deterministically.
"""
from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# Stable failure codes
# ---------------------------------------------------------------------------

FailureCode = Literal[
    "EVIDENCE_NOT_FOUND",
    "MISSING_EVIDENCE",
    "AMOUNT_MISMATCH",
    "AMBIGUOUS_AMOUNT_EVIDENCE",
    "MISSING_VENDOR",
    "VENDOR_EVIDENCE_MISMATCH",
    "PO_PATTERN_MISSING",
    "MISSING_KEY",
    "WRONG_TYPE",
]


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _normalize_text(s: str) -> str:
    """Collapse whitespace runs to single space, strip, casefold."""
    return re.sub(r"\s+", " ", s).strip().casefold()


# ---------------------------------------------------------------------------
# Numeric extraction from evidence strings
# ---------------------------------------------------------------------------

# Matches numbers like: 1234, 1,234, 1234.56, 1,234.56, .99
_NUM_RE = re.compile(r"[\d,]+\.?\d*|\.\d+")

# Currency symbols stripped before numeric extraction
_CURRENCY_RE = re.compile(r"[$€£¥₹]")

# Keywords that disambiguate which number is the "total" amount
_AMOUNT_KEYWORDS = ("total", "amount due", "balance due", "sum")

# Window size (chars) to look back for a keyword before a number
_KEYWORD_WINDOW = 30


def _extract_numbers(evidence: str) -> list[tuple[float, int]]:
    """
    Extract all numeric tokens from *evidence*, returning
    ``[(parsed_float, char_index), ...]``.

    Currency symbols and commas are stripped before parsing.
    """
    cleaned = _CURRENCY_RE.sub("", evidence)
    results: list[tuple[float, int]] = []
    for m in _NUM_RE.finditer(cleaned):
        raw = m.group().replace(",", "")
        if not raw or raw == ".":
            continue
        try:
            results.append((float(raw), m.start()))
        except ValueError:
            continue
    return results


def _disambiguate_amount(
    numbers: list[tuple[float, int]], norm_evidence: str
) -> float | None:
    """
    When *numbers* has >1 entry, try to pick the one preceded by a keyword
    within ``_KEYWORD_WINDOW`` characters.  Returns the chosen number or
    ``None`` if disambiguation fails.
    """
    candidates: list[float] = []
    for value, idx in numbers:
        window_start = max(0, idx - _KEYWORD_WINDOW)
        window = norm_evidence[window_start:idx]
        if any(kw in window for kw in _AMOUNT_KEYWORDS):
            candidates.append(value)
    if len(candidates) == 1:
        return candidates[0]
    return None


# ---------------------------------------------------------------------------
# PO pattern detection
# ---------------------------------------------------------------------------

_PO_RE = re.compile(
    r"(?i)\b(PO|P\.O\.|Purchase\s+Order)\b|PO-?\d+",
)


# ---------------------------------------------------------------------------
# Per-field verification helpers
# ---------------------------------------------------------------------------

def _default_provenance() -> dict:
    """Return provenance dict with all consistent keys at default values."""
    return {
        "vendor": {"grounded": False, "evidence_found_at": -1},
        "amount": {"grounded": False, "parsed_evidence": None, "delta": None},
        "has_po": {"grounded": False, "po_pattern_found": None},
    }


def _check_grounding(
    evidence: str, norm_raw: str
) -> tuple[bool, int]:
    """
    Check whether *evidence* appears as a substring of the raw text.
    Both are normalised before comparison.

    Returns ``(grounded, evidence_found_at)``.
    """
    norm_ev = _normalize_text(evidence)
    idx = norm_raw.find(norm_ev)
    return (idx >= 0, idx)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_extraction(
    raw_text: str,
    extraction: dict,
) -> tuple[bool, list[FailureCode], dict]:
    """
    Verify an evidence-backed extraction payload against *raw_text*.

    Parameters
    ----------
    raw_text   : the original invoice/PO text
    extraction : nested dict ``{field: {value, evidence}, ...}``

    Returns
    -------
    (is_valid, failure_codes, provenance)

    ``provenance`` always has keys ``vendor``, ``amount``, ``has_po``,
    each with consistent sub-keys regardless of pass/fail.
    """
    codes: list[FailureCode] = []
    prov = _default_provenance()
    norm_raw = _normalize_text(raw_text)

    # ---- vendor -----------------------------------------------------------
    _verify_vendor(extraction, norm_raw, codes, prov)

    # ---- amount -----------------------------------------------------------
    _verify_amount(extraction, norm_raw, codes, prov)

    # ---- has_po -----------------------------------------------------------
    _verify_has_po(extraction, norm_raw, codes, prov)

    return (len(codes) == 0, codes, prov)


# ---------------------------------------------------------------------------
# Field verifiers
# ---------------------------------------------------------------------------

def _verify_vendor(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    field = extraction.get("vendor")
    if field is None:
        codes.append("MISSING_KEY")
        return

    if not isinstance(field, dict):
        codes.append("WRONG_TYPE")
        return

    value = field.get("value")
    evidence = field.get("evidence")

    if evidence is not None and not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    # Value checks
    if value is None or (isinstance(value, str) and not value.strip()):
        codes.append("MISSING_VENDOR")
        # Continue to check evidence grounding anyway

    # Evidence checks
    if evidence is None or not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    if not evidence.strip():
        codes.append("MISSING_EVIDENCE")
        return

    # Grounding
    grounded, idx = _check_grounding(evidence, norm_raw)
    prov["vendor"]["evidence_found_at"] = idx
    if not grounded:
        codes.append("EVIDENCE_NOT_FOUND")
        return

    prov["vendor"]["grounded"] = True

    # Vendor-evidence consistency: value must appear in evidence
    if value and isinstance(value, str) and value.strip():
        norm_val = _normalize_text(value)
        norm_ev = _normalize_text(evidence)
        if norm_val not in norm_ev:
            codes.append("VENDOR_EVIDENCE_MISMATCH")


def _verify_amount(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    field = extraction.get("amount")
    if field is None:
        codes.append("MISSING_KEY")
        return

    if not isinstance(field, dict):
        codes.append("WRONG_TYPE")
        return

    value = field.get("value")
    evidence = field.get("evidence")

    # Type check: value must be numeric
    if not isinstance(value, (int, float)):
        codes.append("WRONG_TYPE")
        return

    if evidence is not None and not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    if evidence is None or not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    if not evidence.strip():
        codes.append("MISSING_EVIDENCE")
        return

    # Grounding
    grounded, idx = _check_grounding(evidence, norm_raw)
    prov["amount"]["evidence_found_at"] = idx if "evidence_found_at" in prov["amount"] else idx
    if not grounded:
        codes.append("EVIDENCE_NOT_FOUND")
        return

    prov["amount"]["grounded"] = True

    # Amount math: extract numbers from evidence
    numbers = _extract_numbers(evidence)
    if not numbers:
        codes.append("AMOUNT_MISMATCH")
        return

    if len(numbers) == 1:
        parsed = numbers[0][0]
    else:
        # Disambiguation required
        norm_ev = _normalize_text(evidence)
        # Re-extract from normalized text so indices match
        norm_numbers = _extract_numbers(norm_ev)
        if not norm_numbers:
            codes.append("AMOUNT_MISMATCH")
            return
        parsed = _disambiguate_amount(norm_numbers, norm_ev)
        if parsed is None:
            codes.append("AMBIGUOUS_AMOUNT_EVIDENCE")
            prov["amount"]["parsed_evidence"] = None
            return

    prov["amount"]["parsed_evidence"] = parsed
    delta = abs(parsed - float(value))
    prov["amount"]["delta"] = delta

    if delta > 0.01:
        codes.append("AMOUNT_MISMATCH")


def _verify_has_po(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    field = extraction.get("has_po")
    if field is None:
        codes.append("MISSING_KEY")
        return

    if not isinstance(field, dict):
        codes.append("WRONG_TYPE")
        return

    value = field.get("value")
    evidence = field.get("evidence")

    # Type check: value must be bool
    if not isinstance(value, bool):
        codes.append("WRONG_TYPE")
        return

    if evidence is not None and not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    if evidence is None or not isinstance(evidence, str):
        codes.append("WRONG_TYPE")
        return

    if not evidence.strip():
        codes.append("MISSING_EVIDENCE")
        return

    # Grounding
    grounded, idx = _check_grounding(evidence, norm_raw)
    if not grounded:
        codes.append("EVIDENCE_NOT_FOUND")
        return

    prov["has_po"]["grounded"] = True

    # PO pattern check (only when has_po is True)
    if value is True:
        pattern_found = bool(_PO_RE.search(evidence))
        prov["has_po"]["po_pattern_found"] = pattern_found
        if not pattern_found:
            codes.append("PO_PATTERN_MISSING")
    else:
        prov["has_po"]["po_pattern_found"] = False
