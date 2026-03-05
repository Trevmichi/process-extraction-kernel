"""
conditions.py
Condition DSL for AP process graph edge routing.

Provides a safe, eval-free condition language for process graph edges.

Public API
----------
normalize_condition(raw)   -> str | None  — canonical DSL form or None
parse_condition(expr)      -> ConditionAST — raises ConditionParseError
compile_condition(expr)    -> Callable[[dict], bool]

DSL grammar
-----------
  condition      := comparison (AND comparison)*
  comparison     := identifier op literal
  AND            := "AND" (case-insensitive keyword)
  op             := == | != | > | >= | < | <=
  literal        := number | bool_literal | string_literal
  bool_literal   := true | false
  string_literal := '"' chars '"'
  number         := [-]int | [-]float
  identifier     := [a-zA-Z_][a-zA-Z0-9_]*

No eval, no exec, no arbitrary Python code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Union

# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Comparison:
    """A binary comparison expression: ``left op right``."""
    left:  str   # identifier (APState key)
    op:    str   # one of ==, !=, >, >=, <, <=
    right: Any   # str, int, float, or bool


@dataclass(frozen=True)
class Conjunction:
    """Two or more comparisons joined by AND.

    ``children`` is always a flat tuple of ``Comparison`` instances —
    the parser never produces nested ``Conjunction`` nodes.
    """
    children: tuple[Comparison, ...]


ConditionAST = Union[Comparison, Conjunction]

_VALID_OPS = frozenset({"==", "!=", ">", ">=", "<", "<="})


# ---------------------------------------------------------------------------
# Parse error
# ---------------------------------------------------------------------------

class ConditionParseError(ValueError):
    """Raised when a condition expression cannot be parsed under the DSL."""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_SPEC: list[tuple[str, str]] = [
    ("STRING", r'"(?:[^"\\]|\\.)*"'),   # double-quoted string
    ("FLOAT",  r"-?\d+\.\d+"),          # float (before INT so 1.0 doesn't partially match)
    ("INT",    r"-?\d+"),               # integer
    ("OP",     r">=|<=|!=|==|>|<"),     # operator (multi-char first)
    ("IDENT",  r"[a-zA-Z_][a-zA-Z0-9_]*"),  # identifier or keyword
    ("WS",     r"\s+"),                 # whitespace (skipped)
]

_TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC)
)

_BOOL_KEYWORDS = frozenset({"true", "false"})


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """
    Split *expr* into (kind, value) token pairs (whitespace excluded).

    Raises ``ConditionParseError`` on any unrecognised character.
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            raise ConditionParseError(
                f"Unexpected character at position {pos} in condition: {expr!r}"
            )
        kind = m.lastgroup
        if kind is None:
            raise ConditionParseError(
                f"Tokenizer produced an unknown token at position {pos} in: {expr!r}"
            )
        val  = m.group()
        pos  = m.end()
        if kind == "WS":
            continue
        # Re-classify boolean keywords
        if kind == "IDENT" and val.lower() in _BOOL_KEYWORDS:
            kind = "BOOL"
        # Re-classify AND keyword (case-insensitive)
        elif kind == "IDENT" and val.upper() == "AND":
            kind = "AND"
        tokens.append((kind, val))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_comparison(
    tokens: list[tuple[str, str]], pos: int, expr: str,
) -> tuple[Comparison, int]:
    """Parse a single ``identifier op literal`` starting at *pos*.

    Returns ``(Comparison, new_pos)``.
    """
    if pos + 3 > len(tokens):
        raise ConditionParseError(
            f"Expected comparison (identifier op literal) at token {pos}, "
            f"but only {len(tokens) - pos} token(s) remain in: {expr!r}"
        )

    (k0, v0) = tokens[pos]
    (k1, v1) = tokens[pos + 1]
    (k2, v2) = tokens[pos + 2]

    if k0 != "IDENT":
        raise ConditionParseError(
            f"Left-hand side must be an identifier, got {k0!r} ({v0!r}) in: {expr!r}"
        )

    if k1 != "OP":
        raise ConditionParseError(
            f"Expected operator, got {k1!r} ({v1!r}) in: {expr!r}"
        )

    if v1 not in _VALID_OPS:
        raise ConditionParseError(
            f"Unknown operator {v1!r} in: {expr!r}"
        )

    # Parse the right-hand literal
    if k2 == "BOOL":
        rhs: Any = (v2.lower() == "true")
    elif k2 == "INT":
        rhs = int(v2)
    elif k2 == "FLOAT":
        rhs = float(v2)
    elif k2 == "STRING":
        # Strip surrounding double-quotes; handle escaped quotes
        rhs = v2[1:-1].replace('\\"', '"')
    else:
        raise ConditionParseError(
            f"Right-hand side must be a literal (bool/number/string), "
            f"got {k2!r} ({v2!r}) in: {expr!r}"
        )

    return Comparison(left=v0, op=v1, right=rhs), pos + 3


def parse_condition(expr: str) -> ConditionAST:
    """
    Parse a canonical DSL expression into a ``ConditionAST``.

    Supports single comparisons and AND-chains::

        has_po == false
        status != "BAD_EXTRACTION" AND has_po == false

    Returns ``Comparison`` for a single comparison, ``Conjunction`` for AND-chains.
    Raises ``ConditionParseError`` for anything that doesn't conform.
    """
    if not expr or not expr.strip():
        raise ConditionParseError("Empty condition expression")

    tokens = _tokenize(expr)

    if not tokens:
        raise ConditionParseError(f"No tokens produced from: {expr!r}")

    comp, pos = _parse_comparison(tokens, 0, expr)
    comparisons: list[Comparison] = [comp]

    while pos < len(tokens):
        kind, val = tokens[pos]
        if kind != "AND":
            raise ConditionParseError(
                f"Expected AND or end of expression at token {pos}, "
                f"got {kind!r} ({val!r}) in: {expr!r}"
            )
        pos += 1  # consume AND
        comp, pos = _parse_comparison(tokens, pos, expr)
        comparisons.append(comp)

    if len(comparisons) == 1:
        return comparisons[0]
    return Conjunction(children=tuple(comparisons))


# ---------------------------------------------------------------------------
# Compile: AST → callable predicate
# ---------------------------------------------------------------------------

_OP_FNS: dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def _make_comparison_pred(comp: Comparison) -> Callable[[dict], bool]:
    """Build a predicate for a single ``Comparison`` AST node."""
    key    = comp.left
    op_fn  = _OP_FNS[comp.op]
    target = comp.right

    def predicate(state: dict) -> bool:
        val = state.get(key)
        if val is None:
            return False
        try:
            return op_fn(val, target)
        except TypeError:
            return False

    predicate.__name__ = (
        f"cond_{key}_{comp.op.replace('=','eq').replace('>','gt').replace('<','lt')}"
    )
    return predicate


def compile_condition(expr: str) -> Callable[[dict], bool]:
    """
    Compile a canonical DSL expression to a predicate ``(state: dict) -> bool``.

    Supports single comparisons and AND-chains.  Returns False (rather than
    raising) if a key is absent in *state* or if the comparison raises TypeError.

    Raises ``ConditionParseError`` if *expr* does not parse.
    """
    ast = parse_condition(expr)

    if isinstance(ast, Comparison):
        return _make_comparison_pred(ast)

    # Conjunction: AND-chain — short-circuit via all()
    sub_preds = [_make_comparison_pred(child) for child in ast.children]

    def conjunction_predicate(state: dict) -> bool:
        return all(p(state) for p in sub_preds)

    conjunction_predicate.__name__ = "cond_conjunction"
    return conjunction_predicate


# ---------------------------------------------------------------------------
# Normalization: legacy strings → canonical DSL
# ---------------------------------------------------------------------------

# Exact-match synonym map (case-sensitive keys kept for direct lookup speed;
# the normalize function also tries the lower-cased version).
_SYNONYM_MAP: dict[str, str | None] = {
    # 3-way match → strict match_result Literal
    "match":            'match_result == "MATCH"',
    "MATCH_3_WAY":      'match_result == "MATCH"',
    "match_3_way":      'match_result == "MATCH"',
    "no_match":         'match_result == "NO_MATCH"',
    "successful_match": 'match_result == "MATCH"',
    "within_tolerance": 'match_result == "MATCH"',
    "above_tolerance":  'match_result == "NO_MATCH"',
    "variance":         'match_result == "VARIANCE"',
    "VARIANCE_ABOVE_TOLERANCE": 'match_result == "VARIANCE"',
    # PO presence
    "HAS_PO":           "has_po == true",
    "has_po":           "has_po == true",
    "no_po":            "has_po == false",
    # Approval amount thresholds (legacy 5k)
    "approve":          "amount <= 5000",
    "reject":           "amount > 5000",
    "amount<=thresh":   "amount <= 5000",
    "amount>thresh":    "amount > 5000",
    "approve_or_reject": "amount <= 5000",
    "no_po_approve":    "amount <= 5000",
    "no_po_reject":     "amount > 5000",
    "threshold_amount": "amount <= 5000",
    # Duplicate detection
    "duplicate_detected": 'status == "DUPLICATE"',
    "not_duplicate":    'status != "DUPLICATE"',
    # Ambiguous / not a condition — cannot normalise
    "condition_true":   None,
    "IF_CONDITION":     None,
    "if_condition":     None,
    "SCHEDULE_PAYMENT": None,
    "schedule_payment": None,
}

# Build a case-folded lookup for cheap case-insensitive matching
_SYNONYM_MAP_LOWER: dict[str, str | None] = {
    k.lower(): v for k, v in _SYNONYM_MAP.items()
}

# Inline expression pattern: captures  identifier  op  rest-of-string
_INLINE_SPLIT = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*(>=|<=|!=|==|>|<)\s*(.+)$"
)

# Fields whose unquoted RHS identifiers should be treated as string literals
# and upper-cased (e.g. status == MISSING_DATA → status == "MISSING_DATA")
_STRING_FIELDS: frozenset[str] = frozenset({"status", "match_result"})


def _normalize_rhs(field: str, raw: str) -> str:
    """
    Normalise a raw right-hand side token into a DSL-valid literal string.

    Priority:
    1. boolean keywords → lowercase
    2. numeric → keep as-is
    3. already-quoted string → uppercase inner if field is a string field
    4. bare identifier → wrap in quotes; uppercase if field is a string field
    """
    stripped = raw.strip()

    # Boolean
    if stripped.lower() in ("true", "false"):
        return stripped.lower()

    # Number (int or float)
    try:
        int(stripped)
        return stripped
    except ValueError:
        pass
    try:
        float(stripped)
        return stripped
    except ValueError:
        pass

    # Already-quoted string
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        if field in _STRING_FIELDS:
            inner = stripped[1:-1].upper()
            return f'"{inner}"'
        return stripped

    # Bare identifier → treat as string literal
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", stripped):
        if field in _STRING_FIELDS:
            return f'"{stripped.upper()}"'
        return f'"{stripped}"'

    # Unknown — return as-is and let the parser decide
    return stripped


def _normalize_single(expr: str) -> str | None:
    """Normalise a single comparison expression (no AND).

    Returns canonical DSL string or ``None`` if unrecognised.
    """
    stripped = expr.strip()

    # 1a. Case-sensitive exact match
    if stripped in _SYNONYM_MAP:
        return _SYNONYM_MAP[stripped]

    # 1b. Case-insensitive exact match
    lower = stripped.lower()
    if lower in _SYNONYM_MAP_LOWER:
        return _SYNONYM_MAP_LOWER[lower]

    # 2. Inline expression parsing
    m = _INLINE_SPLIT.match(stripped)
    if m:
        field   = m.group(1)
        op      = m.group(2)
        rhs_raw = m.group(3).strip()
        rhs     = _normalize_rhs(field, rhs_raw)
        return f"{field} {op} {rhs}"

    # 3. Unknown
    return None


def _split_tokens_on_and(
    tokens: list[tuple[str, str]],
) -> list[list[tuple[str, str]]]:
    """Split a token list on AND tokens.

    Returns a list of token-segments (each segment is the tokens for one
    comparison).  AND tokens are consumed and not included in any segment.
    """
    segments: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for tok in tokens:
        if tok[0] == "AND":
            segments.append(current)
            current = []
        else:
            current.append(tok)
    segments.append(current)
    return segments


def _tokens_to_string(tokens: list[tuple[str, str]]) -> str:
    """Reconstruct a DSL sub-expression string from tokens.

    Round-trips correctly for ``_normalize_single()``:
    identifiers/operators verbatim, string literals re-quoted with double
    quotes, bool literals lowercase, numerics verbatim.
    """
    parts: list[str] = []
    for kind, val in tokens:
        if kind == "STRING":
            parts.append(val)          # already double-quoted from tokenizer
        elif kind == "BOOL":
            parts.append(val.lower())  # canonical: true/false
        else:
            parts.append(val)          # IDENT, OP, INT, FLOAT
    return " ".join(parts)


def normalize_condition(raw: str | None) -> str | None:
    """
    Normalise a raw edge-condition string to a canonical DSL expression.

    Returns ``None`` if *raw* is ``None`` (no condition) or if the string
    cannot be mapped to a valid DSL expression (ambiguous legacy labels).

    Supports compound AND expressions by tokenizing first, splitting on
    AND tokens, and normalizing each sub-expression independently.
    """
    if raw is None:
        return None

    stripped = raw.strip()

    # Try tokenizing to detect AND compounds
    try:
        tokens = _tokenize(stripped)
    except ConditionParseError:
        # Tokenizer can't handle it — fall back to single-expression path
        # (handles legacy synonym labels that may not tokenize cleanly)
        return _normalize_single(stripped)

    # Split on AND tokens
    segments = _split_tokens_on_and(tokens)

    if len(segments) == 1:
        # No AND found — use single-expression normalizer
        # (pass original string to preserve synonym-map matching)
        return _normalize_single(stripped)

    # Compound: normalize each sub-expression independently
    parts: list[str] = []
    for seg_tokens in segments:
        sub_expr = _tokens_to_string(seg_tokens)
        norm = _normalize_single(sub_expr)
        if norm is None:
            return None  # can't normalize partial compound
        parts.append(norm)
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# Module-level predicate cache
# ---------------------------------------------------------------------------

_PREDICATE_CACHE: dict[str, Callable[[dict], bool] | None] = {}


def get_predicate(raw: str | None) -> Callable[[dict], bool] | None:
    """
    Return a compiled predicate for *raw*, or ``None`` if it cannot be compiled.

    Results are cached by raw string for performance.
    """
    if raw is None:
        return None
    if raw in _PREDICATE_CACHE:
        return _PREDICATE_CACHE[raw]

    normalized = normalize_condition(raw)
    predicate: Callable[[dict], bool] | None = None
    if normalized is not None:
        try:
            predicate = compile_condition(normalized)
        except ConditionParseError:
            predicate = None

    _PREDICATE_CACHE[raw] = predicate
    return predicate
