"""
tests/test_conditions.py
Unit tests for the Condition DSL (src/conditions.py).

Tests cover:
- normalize_condition  : legacy synonyms + inline expressions
- parse_condition      : valid AST construction and rejection of invalid input
- compile_condition    : correct boolean evaluation against APState-like dicts
- get_predicate        : cache + None handling
"""
from __future__ import annotations

import pytest

from src.conditions import (
    ConditionParseError,
    Comparison,
    Conjunction,
    compile_condition,
    get_predicate,
    normalize_condition,
    parse_condition,
)


# ===========================================================================
# normalize_condition
# ===========================================================================

class TestNormalizeCondition:

    # None passthrough
    def test_none_returns_none(self):
        assert normalize_condition(None) is None

    # Synonym map — spec-required transforms
    def test_match_synonym(self):
        assert normalize_condition("match") == 'match_result == "MATCH"'

    def test_MATCH_3_WAY_synonym(self):
        assert normalize_condition("MATCH_3_WAY") == 'match_result == "MATCH"'

    def test_HAS_PO_synonym(self):
        assert normalize_condition("HAS_PO") == "has_po == true"

    def test_no_po_synonym(self):
        assert normalize_condition("no_po") == "has_po == false"

    def test_no_match_synonym(self):
        assert normalize_condition("no_match") == 'match_result == "NO_MATCH"'

    def test_approve_synonym(self):
        assert normalize_condition("approve") == "amount <= 5000"

    def test_reject_synonym(self):
        assert normalize_condition("reject") == "amount > 5000"

    def test_duplicate_detected_synonym(self):
        assert normalize_condition("duplicate_detected") == 'status == "DUPLICATE"'

    # Ambiguous labels return None
    def test_IF_CONDITION_returns_none(self):
        assert normalize_condition("IF_CONDITION") is None

    def test_if_condition_lower_returns_none(self):
        assert normalize_condition("if_condition") is None

    def test_SCHEDULE_PAYMENT_returns_none(self):
        assert normalize_condition("SCHEDULE_PAYMENT") is None

    # Inline expression normalisation
    def test_status_equals_missing_data(self):
        result = normalize_condition("status==missing_data")
        assert result == 'status == "MISSING_DATA"'

    def test_status_equals_missing_data_with_spaces(self):
        result = normalize_condition("status == missing_data")
        assert result == 'status == "MISSING_DATA"'

    def test_amount_greater_than_10000(self):
        result = normalize_condition("amount>10000")
        assert result == "amount > 10000"

    def test_amount_greater_than_10000_with_spaces(self):
        result = normalize_condition("amount > 10000")
        assert result == "amount > 10000"

    def test_amount_lte_10000(self):
        result = normalize_condition("amount<=10000")
        assert result == "amount <= 10000"

    def test_has_po_equals_false(self):
        result = normalize_condition("has_po==false")
        assert result == "has_po == false"

    def test_has_po_equals_true(self):
        result = normalize_condition("has_po==true")
        assert result == "has_po == true"

    def test_match_3_way_equals_true(self):
        result = normalize_condition("match_3_way==true")
        assert result == "match_3_way == true"

    # Already-canonical DSL forms pass through unchanged (or equivalently normalized)
    def test_already_canonical_has_po_true(self):
        result = normalize_condition("has_po == true")
        assert result == "has_po == true"

    def test_already_canonical_amount_gt(self):
        result = normalize_condition("amount > 10000")
        assert result == "amount > 10000"

    def test_already_canonical_status_string(self):
        result = normalize_condition('status == "APPROVED"')
        assert result == 'status == "APPROVED"'

    # Case-insensitive synonym lookup
    def test_has_po_lowercase_synonym(self):
        assert normalize_condition("has_po") == "has_po == true"

    def test_whitespace_stripped(self):
        assert normalize_condition("  HAS_PO  ") == "has_po == true"

    # AND compound expressions
    def test_compound_and_canonical(self):
        result = normalize_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert result == 'status != "BAD_EXTRACTION" AND has_po == false'

    def test_compound_and_three_way(self):
        result = normalize_condition(
            'status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false'
        )
        assert result == (
            'status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false'
        )

    def test_compound_and_with_unnormalized_sub(self):
        """Sub-expressions should be normalized individually."""
        result = normalize_condition("status!=missing_data AND has_po==false")
        assert result == 'status != "MISSING_DATA" AND has_po == false'

    def test_compound_and_with_unknown_sub_returns_none(self):
        """If any sub-expression cannot be normalised, return None."""
        assert normalize_condition("IF_CONDITION AND has_po == false") is None


# ===========================================================================
# parse_condition
# ===========================================================================

class TestParseCondition:

    # Valid expressions
    def test_parse_has_po_true(self):
        ast = parse_condition("has_po == true")
        assert isinstance(ast, Comparison)
        assert ast.left  == "has_po"
        assert ast.op    == "=="
        assert ast.right is True

    def test_parse_amount_gt_integer(self):
        ast = parse_condition("amount > 10000")
        assert ast.left  == "amount"
        assert ast.op    == ">"
        assert ast.right == 10000

    def test_parse_amount_lte_float(self):
        ast = parse_condition("amount <= 5000.0")
        assert ast.right == 5000.0

    def test_parse_status_eq_string(self):
        ast = parse_condition('status == "MISSING_DATA"')
        assert ast.left  == "status"
        assert ast.op    == "=="
        assert ast.right == "MISSING_DATA"

    def test_parse_match_3_way_false(self):
        ast = parse_condition("match_3_way == false")
        assert ast.right is False

    def test_parse_not_equal(self):
        ast = parse_condition('status != "APPROVED"')
        assert ast.op == "!="

    def test_parse_all_operators(self):
        for op in ("==", "!=", ">", ">=", "<", "<="):
            ast = parse_condition(f"amount {op} 100")
            assert ast.op == op

    # Rejection of invalid input
    def test_rejects_empty_string(self):
        with pytest.raises(ConditionParseError):
            parse_condition("")

    def test_rejects_bare_keyword_no_op(self):
        """A bare keyword like 'HAS_PO' is not a valid DSL expression."""
        with pytest.raises(ConditionParseError):
            parse_condition("HAS_PO")

    def test_rejects_two_tokens(self):
        with pytest.raises(ConditionParseError):
            parse_condition("amount >")

    def test_rejects_four_tokens(self):
        with pytest.raises(ConditionParseError):
            parse_condition("amount > 100 extra")

    def test_rejects_number_on_left(self):
        """Left-hand side must be an identifier, not a number."""
        with pytest.raises(ConditionParseError):
            parse_condition("100 == amount")

    def test_rejects_string_on_left(self):
        with pytest.raises(ConditionParseError):
            parse_condition('"status" == "APPROVED"')

    def test_rejects_unknown_operator(self):
        """Operators like LIKE, ~=, etc. are not in the DSL."""
        with pytest.raises(ConditionParseError):
            parse_condition("status LIKE APPROVED")

    def test_rejects_python_import(self):
        """Python import statement must not parse."""
        with pytest.raises(ConditionParseError):
            parse_condition("import os")

    def test_rejects_python_eval_attempt(self):
        with pytest.raises(ConditionParseError):
            parse_condition("__import__('os')")

    def test_rejects_semicolon_injection(self):
        with pytest.raises(ConditionParseError):
            parse_condition("status == 'ok'; import os")

    def test_rejects_unquoted_string_on_right(self):
        """Bare identifier on RHS without prior normalization should fail."""
        # 'status == APPROVED' — APPROVED is parsed as IDENT (not a literal)
        # but our parser only allows literals on the right side
        with pytest.raises(ConditionParseError):
            parse_condition("status == APPROVED")

    # AND conjunction parsing
    def test_parse_and_two_way(self):
        ast = parse_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert isinstance(ast, Conjunction)
        assert len(ast.children) == 2
        assert ast.children[0] == Comparison(left="status", op="!=", right="BAD_EXTRACTION")
        assert ast.children[1] == Comparison(left="has_po", op="==", right=False)

    def test_parse_and_three_way(self):
        ast = parse_condition(
            'status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false'
        )
        assert isinstance(ast, Conjunction)
        assert len(ast.children) == 3

    def test_single_comparison_not_conjunction(self):
        """A single comparison must return Comparison, never Conjunction."""
        ast = parse_condition("has_po == true")
        assert isinstance(ast, Comparison)
        assert not isinstance(ast, Conjunction)

    def test_conjunction_children_are_flat(self):
        """All children must be Comparison instances (never nested Conjunctions)."""
        ast = parse_condition(
            'status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false'
        )
        assert isinstance(ast, Conjunction)
        for child in ast.children:
            assert isinstance(child, Comparison)

    def test_and_case_insensitive(self):
        """AND keyword should be case-insensitive."""
        ast = parse_condition('has_po == true and amount > 100')
        assert isinstance(ast, Conjunction)
        assert len(ast.children) == 2

    def test_rejects_trailing_and(self):
        with pytest.raises(ConditionParseError):
            parse_condition("amount > 1 AND")

    def test_rejects_leading_and(self):
        with pytest.raises(ConditionParseError):
            parse_condition("AND amount > 1")

    def test_rejects_double_and(self):
        with pytest.raises(ConditionParseError):
            parse_condition("has_po == true AND AND amount > 100")

    def test_rejects_partial_segment_after_and(self):
        """A single identifier after AND can't form a comparison."""
        with pytest.raises(ConditionParseError):
            parse_condition("amount > 1 AND extra")


# ===========================================================================
# compile_condition
# ===========================================================================

class TestCompileCondition:

    def test_has_po_true_with_po(self):
        pred = compile_condition("has_po == true")
        assert pred({"has_po": True})  is True

    def test_has_po_true_without_po(self):
        pred = compile_condition("has_po == true")
        assert pred({"has_po": False}) is False

    def test_has_po_false_without_po(self):
        pred = compile_condition("has_po == false")
        assert pred({"has_po": False}) is True

    def test_amount_gt_10000_above(self):
        pred = compile_condition("amount > 10000")
        assert pred({"amount": 15000.0}) is True

    def test_amount_gt_10000_below(self):
        pred = compile_condition("amount > 10000")
        assert pred({"amount": 5000.0}) is False

    def test_amount_lte_10000_at_boundary(self):
        pred = compile_condition("amount <= 10000")
        assert pred({"amount": 10000.0}) is True

    def test_amount_lte_10000_above(self):
        pred = compile_condition("amount <= 10000")
        assert pred({"amount": 10001.0}) is False

    def test_status_eq_approved(self):
        pred = compile_condition('status == "APPROVED"')
        assert pred({"status": "APPROVED"}) is True
        assert pred({"status": "PENDING"})  is False

    def test_status_neq_duplicate(self):
        pred = compile_condition('status != "DUPLICATE"')
        assert pred({"status": "APPROVED"}) is True
        assert pred({"status": "DUPLICATE"}) is False

    def test_match_3_way_true(self):
        pred = compile_condition("match_3_way == true")
        assert pred({"match_3_way": True})  is True
        assert pred({"match_3_way": False}) is False

    def test_missing_key_returns_false(self):
        """If the state key is absent, predicate returns False (not raises)."""
        pred = compile_condition("has_po == true")
        assert pred({}) is False

    def test_type_mismatch_returns_false(self):
        """Comparing string to int should return False, not raise."""
        pred = compile_condition("amount > 10000")
        assert pred({"amount": "not_a_number"}) is False

    # AND conjunction compilation
    def test_conjunction_both_true(self):
        pred = compile_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert pred({"status": "", "has_po": False}) is True

    def test_conjunction_first_false(self):
        """BAD_EXTRACTION guard must block even when has_po matches."""
        pred = compile_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert pred({"status": "BAD_EXTRACTION", "has_po": False}) is False

    def test_conjunction_second_false(self):
        pred = compile_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert pred({"status": "", "has_po": True}) is False

    def test_conjunction_missing_key_returns_false(self):
        pred = compile_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert pred({"status": ""}) is False  # has_po missing → False

    def test_conjunction_three_way(self):
        pred = compile_condition(
            'status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false'
        )
        assert pred({"status": "", "has_po": False}) is True
        assert pred({"status": "BAD_EXTRACTION", "has_po": False}) is False
        assert pred({"status": "MISSING_DATA", "has_po": False}) is False
        assert pred({"status": "", "has_po": True}) is False


# ===========================================================================
# get_predicate (cache + None handling)
# ===========================================================================

class TestGetPredicate:

    def test_none_input_returns_none(self):
        assert get_predicate(None) is None

    def test_valid_condition_returns_callable(self):
        pred = get_predicate("has_po == true")
        assert callable(pred)

    def test_synonym_resolves_to_callable(self):
        pred = get_predicate("HAS_PO")
        assert callable(pred)
        assert pred({"has_po": True})  is True
        assert pred({"has_po": False}) is False

    def test_ambiguous_condition_returns_none(self):
        assert get_predicate("IF_CONDITION") is None

    def test_unknown_condition_returns_none(self):
        assert get_predicate("TOTALLY_UNKNOWN_LABEL") is None

    def test_caching_same_object_returned(self):
        """Calling get_predicate twice with same input returns same object."""
        pred1 = get_predicate("amount > 10000")
        pred2 = get_predicate("amount > 10000")
        assert pred1 is pred2

    def test_inline_expression_resolves(self):
        pred = get_predicate("amount>10000")
        assert pred is not None
        assert pred({"amount": 20000}) is True
        assert pred({"amount": 5000})  is False

    def test_compound_and_resolves(self):
        pred = get_predicate('status != "BAD_EXTRACTION" AND has_po == false')
        assert callable(pred)
        assert pred({"status": "", "has_po": False}) is True
        assert pred({"status": "BAD_EXTRACTION", "has_po": False}) is False
