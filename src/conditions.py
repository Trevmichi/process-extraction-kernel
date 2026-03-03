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
  condition      := identifier op literal
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


# Currently only one node type; extend here for AND/OR later
ConditionAST = Comparison

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
        val  = m.group()
        pos  = m.end()
        if kind == "WS":
            continue
        # Re-classify boolean keywords
        if kind == "IDENT" and val.lower() in _BOOL_KEYWORDS:
            kind = "BOOL"
        tokens.append((kind, val))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_condition(expr: str) -> ConditionAST:
    """
    Parse a canonical DSL expression into a ``ConditionAST``.

    The expression must be exactly ``<identifier> <op> <literal>``.
    Raises ``ConditionParseError`` for anything that doesn't conform.
    """
    if not expr or not expr.strip():
        raise ConditionParseError("Empty condition expression")

    tokens = _tokenize(expr)

    if len(tokens) != 3:
        raise ConditionParseError(
            f"Expected exactly 3 tokens (identifier op literal), "
            f"got {len(tokens)} in: {expr!r}"
        )

    (k0, v0), (k1, v1), (k2, v2) = tokens

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

    return Comparison(left=v0, op=v1, right=rhs)


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


def compile_condition(expr: str) -> Callable[[dict], bool]:
    """
    Compile a canonical DSL expression to a predicate ``(state: dict) -> bool``.

    The predicate reads ``state[identifier]`` and applies the operator
    against the literal.  Returns False (rather than raising) if the key
    is absent in *state* or if the comparison raises TypeError.

    Raises ``ConditionParseError`` if *expr* does not parse.
    """
    ast = parse_condition(expr)
    key    = ast.left
    op_fn  = _OP_FNS[ast.op]
    target = ast.right

    def predicate(state: dict) -> bool:
        val = state.get(key)
        if val is None:
            return False
        try:
            return op_fn(val, target)
        except TypeError:
            return False

    predicate.__name__ = f"cond_{key}_{ast.op.replace('=','eq').replace('>','gt').replace('<','lt')}"
    return predicate


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


def normalize_condition(raw: str | None) -> str | None:
    """
    Normalise a raw edge-condition string to a canonical DSL expression.

    Returns ``None`` if *raw* is ``None`` (no condition) or if the string
    cannot be mapped to a valid DSL expression (ambiguous legacy labels).

    Normalisation steps:
    1. Strip surrounding whitespace.
    2. Exact synonym lookup (case-sensitive, then case-folded).
    3. Inline expression pattern (``identifier op value``).
    4. Return ``None`` for anything unrecognised.
    """
    if raw is None:
        return None

    stripped = raw.strip()

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
