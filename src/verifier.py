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
from datetime import date
from typing import Literal

from .verifier_registry import build_legacy_validator_registry

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
    "DATE_MISSING_KEY",
    "DATE_WRONG_TYPE",
    "DATE_EVIDENCE_NOT_FOUND",
    "DATE_PARSE_FAILED",
    "DATE_AMBIGUOUS",
    "DATE_VALUE_MISMATCH",
    "TAX_MISSING_KEY",
    "TAX_WRONG_TYPE",
    "TAX_EVIDENCE_NOT_FOUND",
    "TAX_MISSING_EVIDENCE",
    "TAX_PARSE_FAILED",
    "TAX_ANCHOR_MISSING",
    "TAX_AMBIGUOUS_EVIDENCE",
    "TAX_AMOUNT_MISMATCH",
]


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _normalize_text(s: str) -> str:
    """Collapse whitespace runs to single space, strip, casefold.

    Args:
      s: str: 

    Returns:

    """
    return re.sub(r"\s+", " ", s).strip().casefold()


# ---------------------------------------------------------------------------
# Numeric extraction from evidence strings
# ---------------------------------------------------------------------------

# Matches numbers like: 1234, 1,234, 1234.56, 1,234.56, .99
_NUM_RE = re.compile(r"[\d,]+\.?\d*|\.\d+")

# Currency symbols stripped before numeric extraction
_CURRENCY_RE = re.compile(r"[$€£¥₹]")

# Keywords that disambiguate which number is the "total" amount
_AMOUNT_KEYWORDS = ("total", "amount due", "balance due", "sum", "due", "amount")

# Window size (chars) to look back for a keyword before a number
_KEYWORD_WINDOW = 30


def _extract_numbers(evidence: str) -> list[tuple[float, int]]:
    """Extract all numeric tokens from *evidence*, returning
    ``[(parsed_float, char_index), ...]``.
    
    Currency symbols and commas are stripped before parsing.

    Args:
      evidence: str: 

    Returns:

    """
    # Replace with space instead of empty string to preserve match indices
    cleaned = _CURRENCY_RE.sub(" ", evidence)
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
    """When *numbers* has >1 entry, try to pick the one preceded by a keyword
    within ``_KEYWORD_WINDOW`` characters.  Returns the chosen number or
    ``None`` if disambiguation fails.

    Args:
      numbers: list[tuple[float: 
      int]]: 
      norm_evidence: str: 

    Returns:

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
    r"\b(PO|Purchase\s+Order|REF|Reference)\b|\bP\.O\.(?:\s|$|#)|(?:PO|REF)-?\d+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API for eval/audit tooling
# ---------------------------------------------------------------------------
# These are read-only exports consumed by eval_audit.py and tests.
# They must remain backward-compatible; if you rename or remove a private
# symbol, update the alias here (or update eval_audit accordingly).
MONEY_RE = _NUM_RE
CURRENCY_RE = _CURRENCY_RE
PO_RE = _PO_RE
AMOUNT_KEYWORDS = _AMOUNT_KEYWORDS
KEYWORD_WINDOW = _KEYWORD_WINDOW
normalize_text = _normalize_text

# Date token patterns (ISO and slash-delimited)
_DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b")

# Tax anchor keywords and value extraction
_TAX_ANCHOR_RE = re.compile(r"\b(tax|vat|gst)\b", re.IGNORECASE)
_TAX_ANCHOR_VALUE_RE = re.compile(
    r"\b(?:tax|vat|gst)\b[^0-9\-]{0,24}([-+]?(?:\d[\d,]*\.?\d*|\.\d+))",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Per-field verification helpers
# ---------------------------------------------------------------------------

def _default_provenance() -> dict:
    """Build a provenance payload with stable keys and default values.

    Returns:
      dict: Canonical provenance object for vendor, amount, and has_po fields.
    """
    return {
        "vendor": {"grounded": False, "evidence_found_at": -1},
        "amount": {"grounded": False, "parsed_evidence": None, "delta": None},
        "has_po": {"grounded": False, "po_pattern_found": None},
    }


def _check_grounding(
    evidence: str, norm_raw: str
) -> tuple[bool, int]:
    """Check whether *evidence* appears as a substring of the raw text.
    Both are normalised before comparison.
    
    Returns ``(grounded, evidence_found_at)``.

    Args:
      evidence: str: 
      norm_raw: str: 

    Returns:

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
    """Verify an evidence-backed extraction payload against *raw_text*.

    Args:
      raw_text(the original invoice/PO text): 
      extraction(nested dict ``{field: {value, evidence}, ...}``): 
      raw_text: str: 
      extraction: dict: 

    Returns:

    
    """
    codes: list[FailureCode] = []
    prov = _default_provenance()
    norm_raw = _normalize_text(raw_text)

    registry = build_legacy_validator_registry()
    for spec in registry.ordered_specs():
        if spec.optional and spec.field_name not in extraction:
            continue
        spec.validator(extraction, norm_raw, codes, prov)

    # ROLLBACK: If registry path fails, restore direct calls:
    #   _verify_vendor(extraction, norm_raw, codes, prov)
    #   _verify_amount(extraction, norm_raw, codes, prov)
    #   _verify_has_po(extraction, norm_raw, codes, prov)

    return (len(codes) == 0, codes, prov)


# ---------------------------------------------------------------------------
# Field verifiers
# ---------------------------------------------------------------------------

def _verify_vendor(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    """

    Args:
      extraction: dict: 
      norm_raw: str: 
      codes: list: 
      prov: dict: 

    Returns:

    """
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
    """

    Args:
      extraction: dict: 
      norm_raw: str: 
      codes: list: 
      prov: dict: 

    Returns:

    """
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

    parsed: float | None = None
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

    if parsed is None:
        codes.append("AMOUNT_MISMATCH")
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
    """

    Args:
      extraction: dict: 
      norm_raw: str: 
      codes: list: 
      prov: dict: 

    Returns:

    """
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

    # Null-tolerance: has_po=False with None/empty evidence is valid —
    # there is no PO to ground when the invoice has none.
    if value is False and (
        evidence is None
        or not isinstance(evidence, str)
        or not evidence.strip()
    ):
        prov["has_po"]["grounded"] = True
        prov["has_po"]["po_pattern_found"] = False
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
        
        # If the direct evidence lacks a PO keyword, check the surrounding text context
        if not pattern_found:
            norm_ev = _normalize_text(evidence)
            window_start = max(0, idx - 50)
            window_end = min(len(norm_raw), idx + len(norm_ev) + 50)
            pattern_found = bool(_PO_RE.search(norm_raw[window_start:window_end]))
            
        prov["has_po"]["po_pattern_found"] = pattern_found
        if not pattern_found:
            codes.append("PO_PATTERN_MISSING")
    else:
        prov["has_po"]["po_pattern_found"] = False


# ---------------------------------------------------------------------------
# invoice_date verification
# ---------------------------------------------------------------------------

def _parse_date_token(token: str) -> tuple[str | None, str | None]:
    """Parse one date token into ISO YYYY-MM-DD.

    Returns (iso_date, error_code) where exactly one is non-None.
    """
    stripped = token.strip()
    m_iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", stripped)
    if m_iso:
        year, month, day = map(int, m_iso.groups())
        try:
            return date(year, month, day).isoformat(), None
        except ValueError:
            return None, "DATE_PARSE_FAILED"

    m_slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", stripped)
    if not m_slash:
        return None, "DATE_PARSE_FAILED"

    first, second, year = map(int, m_slash.groups())

    if first <= 0 or second <= 0:
        return None, "DATE_PARSE_FAILED"
    if first > 12 and second > 12:
        return None, "DATE_PARSE_FAILED"

    # Disambiguation: if only one component > 12, it must be day
    if first > 12 and second <= 12:
        day, month = first, second
    elif second > 12 and first <= 12:
        month, day = first, second
    elif first == second:
        month, day = first, second
    else:
        # Both <= 12; cannot disambiguate
        return None, "DATE_AMBIGUOUS"

    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, "DATE_PARSE_FAILED"


def _extract_evidence_invoice_date(evidence: str) -> tuple[str | None, str | None]:
    """Extract a deterministic ISO invoice date from evidence text."""
    tokens = _DATE_TOKEN_RE.findall(evidence)
    if not tokens:
        return None, "DATE_PARSE_FAILED"

    parsed_dates: list[str] = []
    saw_ambiguous = False
    for token in tokens:
        parsed, err = _parse_date_token(token)
        if err == "DATE_AMBIGUOUS":
            saw_ambiguous = True
            continue
        if err is not None:
            continue
        if parsed is not None:
            parsed_dates.append(parsed)

    unique_dates = sorted(set(parsed_dates))
    if saw_ambiguous:
        return None, "DATE_AMBIGUOUS"
    if len(unique_dates) == 0:
        return None, "DATE_PARSE_FAILED"
    if len(unique_dates) > 1:
        return None, "DATE_AMBIGUOUS"
    return unique_dates[0], None


def _verify_invoice_date(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    """Verify optional invoice_date field with deterministic parsing rules."""
    prov.setdefault(
        "invoice_date",
        {
            "grounded": False,
            "evidence_found_at": -1,
            "normalized_value": None,
            "normalized_evidence": None,
        },
    )

    field = extraction.get("invoice_date")
    if field is None:
        codes.append("DATE_MISSING_KEY")
        return

    if not isinstance(field, dict):
        codes.append("DATE_WRONG_TYPE")
        return

    if "value" not in field or "evidence" not in field:
        codes.append("DATE_MISSING_KEY")
        return

    value = field.get("value")
    evidence = field.get("evidence")

    if not isinstance(value, str):
        codes.append("DATE_WRONG_TYPE")
        return

    if not isinstance(evidence, str):
        codes.append("DATE_WRONG_TYPE")
        return

    if not value.strip() or not evidence.strip():
        codes.append("DATE_MISSING_KEY")
        return

    grounded, idx = _check_grounding(evidence, norm_raw)
    prov["invoice_date"]["evidence_found_at"] = idx
    if not grounded:
        codes.append("DATE_EVIDENCE_NOT_FOUND")
        return

    prov["invoice_date"]["grounded"] = True

    value_iso, value_err = _parse_date_token(value)
    if value_err is not None:
        codes.append(value_err)
        return

    evidence_iso, evidence_err = _extract_evidence_invoice_date(evidence)
    if evidence_err is not None:
        codes.append(evidence_err)
        return

    prov["invoice_date"]["normalized_value"] = value_iso
    prov["invoice_date"]["normalized_evidence"] = evidence_iso

    if value_iso != evidence_iso:
        codes.append("DATE_VALUE_MISMATCH")


# ---------------------------------------------------------------------------
# tax_amount verification
# ---------------------------------------------------------------------------

def _extract_tax_amount_from_evidence(evidence: str) -> tuple[float | None, str | None]:
    """Extract deterministic tax amount from evidence text."""
    if not _TAX_ANCHOR_RE.search(evidence):
        return None, "TAX_ANCHOR_MISSING"

    cleaned = _CURRENCY_RE.sub(" ", evidence)
    values: list[float] = []
    for match in _TAX_ANCHOR_VALUE_RE.finditer(cleaned):
        raw = match.group(1).replace(",", "")
        try:
            values.append(float(raw))
        except ValueError:
            continue

    unique_values = sorted(set(values))
    if len(unique_values) == 0:
        return None, "TAX_PARSE_FAILED"
    if len(unique_values) > 1:
        return None, "TAX_AMBIGUOUS_EVIDENCE"
    return unique_values[0], None


def _verify_tax_amount(
    extraction: dict, norm_raw: str,
    codes: list, prov: dict,
) -> None:
    """Verify optional tax_amount field with anchor-aware deterministic parsing."""
    prov.setdefault(
        "tax_amount",
        {
            "grounded": False,
            "evidence_found_at": -1,
            "anchor_found": None,
            "parsed_evidence": None,
            "delta": None,
        },
    )

    field = extraction.get("tax_amount")
    if field is None:
        codes.append("TAX_MISSING_KEY")
        return

    if not isinstance(field, dict):
        codes.append("TAX_WRONG_TYPE")
        return

    if "value" not in field or "evidence" not in field:
        codes.append("TAX_MISSING_KEY")
        return

    value = field.get("value")
    evidence = field.get("evidence")

    if not isinstance(value, (int, float)):
        codes.append("TAX_WRONG_TYPE")
        return

    if not isinstance(evidence, str):
        codes.append("TAX_WRONG_TYPE")
        return

    if not evidence.strip():
        codes.append("TAX_MISSING_EVIDENCE")
        return

    grounded, idx = _check_grounding(evidence, norm_raw)
    prov["tax_amount"]["evidence_found_at"] = idx
    if not grounded:
        codes.append("TAX_EVIDENCE_NOT_FOUND")
        return

    prov["tax_amount"]["grounded"] = True

    anchor_found = bool(_TAX_ANCHOR_RE.search(evidence))
    prov["tax_amount"]["anchor_found"] = anchor_found
    if not anchor_found:
        codes.append("TAX_ANCHOR_MISSING")
        return

    parsed, err = _extract_tax_amount_from_evidence(evidence)
    if err is not None:
        codes.append(err)
        return

    prov["tax_amount"]["parsed_evidence"] = parsed
    delta = abs(float(value) - float(parsed))
    prov["tax_amount"]["delta"] = delta
    if delta > 0.01:
        codes.append("TAX_AMOUNT_MISMATCH")
