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
    ConditionDiagnostic,
    NormalizationProvenance,
    TypeWarning,
    _FIELD_TYPES,
    _PREDICATE_CACHE,
    _SYNONYM_MAP,
    compile_condition,
    diagnose_condition,
    get_predicate,
    normalize_condition,
    parse_condition,
    validate_condition_types,
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
        assert normalize_condition("approve") == "amount <= 10000"

    def test_reject_synonym(self):
        assert normalize_condition("reject") == "amount > 10000"

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


# ===========================================================================
# diagnose_condition (structured diagnostics)
# ===========================================================================

class TestConditionDiagnostic:

    def test_diagnose_none_input(self):
        d = diagnose_condition(None)
        assert d.raw is None
        assert d.normalized is None
        assert d.parsed is False
        assert d.error is None
        assert d.provenance is not None
        assert d.provenance.kind == "null_input"

    def test_diagnose_synonym(self):
        d = diagnose_condition("HAS_PO")
        assert d.normalized == "has_po == true"
        assert d.parsed is True
        assert d.error is None
        assert d.provenance.kind == "synonym"
        assert d.provenance.synonym_key == "HAS_PO"

    def test_diagnose_identity(self):
        d = diagnose_condition("has_po == true")
        assert d.normalized == "has_po == true"
        assert d.parsed is True
        assert d.provenance.kind == "identity"

    def test_diagnose_inline_canonicalization(self):
        d = diagnose_condition("status==missing_data")
        assert d.normalized == 'status == "MISSING_DATA"'
        assert d.parsed is True
        assert d.provenance.kind == "inline_canonicalization"

    def test_diagnose_compound(self):
        d = diagnose_condition('status != "BAD_EXTRACTION" AND has_po == false')
        assert d.parsed is True
        assert d.provenance.kind == "compound"
        assert d.provenance.segments is not None
        assert len(d.provenance.segments) == 2

    def test_diagnose_unparseable(self):
        d = diagnose_condition("IF_CONDITION")
        assert d.normalized is None
        assert d.parsed is False
        assert d.error == "normalization_failed"
        assert d.provenance.kind == "synonym"
        # IF_CONDITION maps to None in synonym map (ambiguous)

    def test_diagnose_truly_unknown(self):
        d = diagnose_condition("TOTALLY_UNKNOWN_LABEL_XYZ")
        assert d.normalized is None
        assert d.parsed is False
        assert d.error == "normalization_failed"
        assert d.provenance.kind == "unparseable"

    def test_diagnose_ast_populated(self):
        d = diagnose_condition("amount > 10000")
        assert d.ast is not None
        assert d.ast == parse_condition("amount > 10000")

    def test_diagnose_type_warnings_populated(self):
        d = diagnose_condition('has_po == "yes"')
        assert d.parsed is True
        assert len(d.type_warnings) > 0
        assert d.type_warnings[0].field == "has_po"

    def test_diagnose_does_not_affect_cache(self):
        cache_before = dict(_PREDICATE_CACHE)
        diagnose_condition("amount > 99999")
        cache_after = dict(_PREDICATE_CACHE)
        assert cache_before == cache_after


# ===========================================================================
# NormalizationProvenance
# ===========================================================================

class TestNormalizationProvenance:

    def test_provenance_synonym_case_sensitive(self):
        d = diagnose_condition("MATCH_3_WAY")
        assert d.provenance.kind == "synonym"
        assert d.provenance.synonym_key == "MATCH_3_WAY"

    def test_provenance_synonym_case_insensitive(self):
        d = diagnose_condition("Match_3_Way")
        assert d.provenance.kind == "synonym"
        assert d.provenance.synonym_key == "match_3_way"

    def test_provenance_compound_mixed_segments(self):
        d = diagnose_condition("HAS_PO AND amount > 5000")
        assert d.provenance.kind == "compound"
        segs = d.provenance.segments
        assert segs[0].kind == "synonym"
        assert segs[1].kind in ("identity", "inline_canonicalization")

    def test_provenance_frozen(self):
        p = NormalizationProvenance(kind="identity")
        with pytest.raises(AttributeError):
            p.kind = "changed"  # type: ignore[misc]


# ===========================================================================
# validate_condition_types (static type checking)
# ===========================================================================

class TestValidateConditionTypes:

    def test_valid_bool_field(self):
        ast = parse_condition("has_po == true")
        assert validate_condition_types(ast) == []

    def test_valid_string_field(self):
        ast = parse_condition('status == "APPROVED"')
        assert validate_condition_types(ast) == []

    def test_valid_numeric_field(self):
        ast = parse_condition("amount > 10000")
        assert validate_condition_types(ast) == []

    def test_float_rhs_on_numeric_field(self):
        ast = parse_condition("amount > 10000.50")
        assert validate_condition_types(ast) == []

    def test_type_mismatch_bool_vs_string(self):
        ast = parse_condition('has_po == "yes"')
        warnings = validate_condition_types(ast)
        assert len(warnings) == 1
        assert warnings[0].field == "has_po"
        assert warnings[0].actual_rhs_type is str

    def test_type_mismatch_string_vs_bool(self):
        ast = parse_condition("status == true")
        warnings = validate_condition_types(ast)
        assert len(warnings) == 1
        assert warnings[0].field == "status"
        assert warnings[0].actual_rhs_type is bool

    def test_unknown_field_skipped(self):
        ast = parse_condition("unknown_field == true")
        assert validate_condition_types(ast) == []

    def test_conjunction_all_checked(self):
        ast = parse_condition('has_po == "yes" AND status == true')
        warnings = validate_condition_types(ast)
        assert len(warnings) == 2
        fields = {w.field for w in warnings}
        assert fields == {"has_po", "status"}

    def test_custom_field_types(self):
        ast = parse_condition("amount > 10000")
        # With custom registry that says amount is str, should warn
        warnings = validate_condition_types(ast, field_types={"amount": str})
        assert len(warnings) == 1
        assert warnings[0].field == "amount"

    def test_string_ordinal_warning(self):
        ast = parse_condition('status > "A"')
        warnings = validate_condition_types(ast)
        assert any("ordinal" in w.message.lower() for w in warnings)


# ===========================================================================
# _FIELD_TYPES sync with APState
# ===========================================================================

class TestFieldTypeSync:

    def test_field_types_subset_of_apstate(self):
        from src.agent.state import APState
        annotations = APState.__annotations__
        for field_name in _FIELD_TYPES:
            assert field_name in annotations, (
                f"_FIELD_TYPES has {field_name!r} but APState does not"
            )


# ===========================================================================
# diagnose_condition ↔ normalize_condition consistency
# ===========================================================================

class TestDiagnoseNormalizeConsistency:

    @pytest.mark.parametrize("raw", list(_SYNONYM_MAP.keys()))
    def test_synonym_map_consistency(self, raw: str):
        d = diagnose_condition(raw)
        assert d.normalized == normalize_condition(raw)

    @pytest.mark.parametrize("raw", [
        "has_po == true",
        "amount > 10000",
        'status == "APPROVED"',
        "status==missing_data",
        "amount<=5000",
        'status != "BAD_EXTRACTION" AND has_po == false',
    ])
    def test_inline_consistency(self, raw: str):
        d = diagnose_condition(raw)
        assert d.normalized == normalize_condition(raw)


class TestThresholdConsistency:
    """Verify all threshold synonyms use the canonical ontology constant."""

    def test_threshold_synonyms_use_ontology_constant(self):
        from src.ontology import (
            CONDITION_AMOUNT_ABOVE_THRESHOLD,
            CONDITION_AMOUNT_AT_OR_BELOW_THRESHOLD,
        )
        threshold_keys = {
            "approve", "reject", "amount<=thresh", "amount>thresh",
            "approve_or_reject", "no_po_approve", "no_po_reject",
            "threshold_amount",
        }
        for key in threshold_keys:
            val = _SYNONYM_MAP[key]
            assert val in (
                CONDITION_AMOUNT_ABOVE_THRESHOLD,
                CONDITION_AMOUNT_AT_OR_BELOW_THRESHOLD,
            ), f"Synonym {key!r} maps to {val!r}, expected one of the ontology constants"
