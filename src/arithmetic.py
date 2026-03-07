"""
src/arithmetic.py
Deterministic arithmetic-consistency checks for invoice text.

Pure source-text validation: "do the numbers printed on the invoice add up?"
No LLM involvement, no extraction-payload dependency.

Arithmetic failures are usually non-recoverable — they reflect inconsistencies
in the source document itself, not LLM extraction errors.  Re-extraction cannot
fix a document where subtotal + tax != total.
"""
from __future__ import annotations

import re
from typing import Literal

from .verifier import CURRENCY_RE, MONEY_RE, normalize_text

# ---------------------------------------------------------------------------
# Failure codes (also added to verifier.FailureCode Literal union)
# ---------------------------------------------------------------------------

ArithFailureCode = Literal[
    "ARITH_TOTAL_MISMATCH",
    "ARITH_TAX_RATE_MISMATCH",
]

# ---------------------------------------------------------------------------
# Tolerance
# ---------------------------------------------------------------------------

_TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Keyword classification
# ---------------------------------------------------------------------------

# Order matters: more specific keywords must come before less specific ones
# so that "subtotal" matches before "total".
_ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("subtotal", ("subtotal", "sub total", "sub-total")),
    ("tax", ("tax", "vat", "gst")),
    ("fee", ("shipping", "freight", "surcharge", "fee", "handling",
             "hazard pay", "processing fee", "environmental")),
    ("total", ("total", "amount due", "balance due", "final balance",
               "total due", "final total")),
]

_KEYWORD_WINDOW = 40


def _classify_numbers(text: str) -> list[dict]:
    """Extract money-like numbers from *text* and tag each with a role.

    Returns a list of ``{"value": float, "role": str|None, "keyword": str|None}``
    sorted by position in text.  Role is one of "subtotal", "tax", "fee",
    "total", or ``None`` if no keyword was found nearby.

    Classification uses closest-keyword-wins: the keyword whose end position
    is nearest to the number wins, preventing "subtotal" from shadowing a
    later "total" in the same look-back window.
    """
    norm = normalize_text(text)
    cleaned = CURRENCY_RE.sub(" ", norm)

    results: list[dict] = []
    for m in MONEY_RE.finditer(cleaned):
        raw = m.group().replace(",", "")
        if not raw or raw == ".":
            continue
        # Skip percentage values (e.g., "8%" from "Tax (8%)")
        after = cleaned[m.end():m.end() + 3].lstrip()
        if after.startswith("%"):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue

        # Look back in the window for keywords — closest wins
        window_start = max(0, m.start() - _KEYWORD_WINDOW)
        window = cleaned[window_start:m.start()]

        best_role: str | None = None
        best_keyword: str | None = None
        best_pos: int = -1  # end position of keyword in window
        for role_name, keywords in _ROLE_KEYWORDS:
            for kw in keywords:
                pos = window.rfind(kw)
                if pos >= 0:
                    end_pos = pos + len(kw)
                    if end_pos > best_pos:
                        best_pos = end_pos
                        best_role = role_name
                        best_keyword = kw

        results.append({"value": value, "role": best_role, "keyword": best_keyword})

    return results


def _get_by_role(classified: list[dict], role: str) -> list[float]:
    """Return all values with the given role."""
    return [c["value"] for c in classified if c["role"] == role]


# ---------------------------------------------------------------------------
# Tax rate regex
# ---------------------------------------------------------------------------

_TAX_RATE_RE = re.compile(
    r"\b(?:tax|vat|gst)\s*\(?(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Check A: Subtotal + Tax + Fees = Total
# ---------------------------------------------------------------------------

def _check_total_sum(classified: list[dict]) -> tuple[str | None, dict | None]:
    """Verify subtotal + taxes + fees ≈ total.

    Returns (failure_code_or_None, provenance_or_None).
    Returns (None, None) if the check cannot run (missing subtotal or total).
    """
    subtotals = _get_by_role(classified, "subtotal")
    totals = _get_by_role(classified, "total")

    if not subtotals or not totals:
        return None, None

    # Use the last subtotal and last total (last-wins, matches verifier pattern)
    subtotal = subtotals[-1]
    total = totals[-1]
    taxes = sum(_get_by_role(classified, "tax"))
    fees = sum(_get_by_role(classified, "fee"))

    expected = subtotal + taxes + fees
    delta = round(abs(expected - total), 2)

    prov = {
        "subtotal": subtotal,
        "taxes": taxes,
        "fees": fees,
        "expected": round(expected, 2),
        "actual": total,
        "delta": delta,
    }

    if delta > _TOLERANCE:
        return "ARITH_TOTAL_MISMATCH", prov
    return None, prov


# ---------------------------------------------------------------------------
# Check B: Tax Rate Consistency
# ---------------------------------------------------------------------------

def _check_tax_rate(raw_text: str, classified: list[dict]) -> tuple[str | None, dict | None]:
    """Verify stated tax rate * subtotal ≈ tax amount.

    Returns (failure_code_or_None, provenance_or_None).
    Returns (None, None) if the check cannot run.
    """
    norm = normalize_text(raw_text)
    m = _TAX_RATE_RE.search(norm)
    if m is None:
        return None, None

    rate_pct = float(m.group(1))

    subtotals = _get_by_role(classified, "subtotal")
    taxes = _get_by_role(classified, "tax")

    if not subtotals or not taxes:
        return None, None

    subtotal = subtotals[-1]
    stated_tax = taxes[-1]
    computed_tax = subtotal * rate_pct / 100.0
    delta = round(abs(computed_tax - stated_tax), 2)

    prov = {
        "rate_pct": rate_pct,
        "computed": round(computed_tax, 2),
        "stated": stated_tax,
        "delta": delta,
    }

    if delta > _TOLERANCE:
        return "ARITH_TAX_RATE_MISMATCH", prov
    return None, prov


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_arithmetic(raw_text: str) -> tuple[list[str], dict | None]:
    """Check arithmetic consistency of numbers in *raw_text*.

    Returns ``(codes, provenance)`` where *codes* is a list of ``ARITH_*``
    failure code strings and *provenance* is a compact dict of per-check
    results.  Returns ``([], None)`` if no checks could run (text lacks
    sufficient structure such as subtotals or tax rates).

    This is a pure source-text consistency check with no dependency on the
    extraction payload.
    """
    classified = _classify_numbers(raw_text)

    codes: list[str] = []
    checks_run: list[str] = []
    detail: dict = {}

    # Check A: total sum
    code_a, prov_a = _check_total_sum(classified)
    if prov_a is not None:
        checks_run.append("total_sum")
        detail["total_sum"] = prov_a
        if code_a is not None:
            codes.append(code_a)

    # Check B: tax rate
    code_b, prov_b = _check_tax_rate(raw_text, classified)
    if prov_b is not None:
        checks_run.append("tax_rate")
        detail["tax_rate"] = prov_b
        if code_b is not None:
            codes.append(code_b)

    # No checks ran → return None provenance (no audit event should be emitted)
    if not checks_run:
        return [], None

    return codes, {
        "checks_run": checks_run,
        "passed": len(codes) == 0,
        "codes": list(codes),
        **detail,
    }
