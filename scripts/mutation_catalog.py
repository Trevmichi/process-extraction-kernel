"""
Curated mutation catalog for deterministic-layer smoke testing.

Phase 1 scope:
- Low-noise, domain-specific mutants only
- Deterministic layers only (conditions/router/verifier/linter/invariants)
- Small budget suitable for local smoke checks
"""
from __future__ import annotations

MUTATION_CATALOG: list[dict] = [
    {
        "id": "M001_conditions_reject_gt_to_gte",
        "target_file": "src/conditions.py",
        "description": "Flip reject threshold operator from > to >=",
        "mutation_type": "dsl_operator_flip",
        "apply_rule": {
            "kind": "replace_one",
            "old": '"reject":           "amount > 5000",',
            "new": '"reject":           "amount >= 5000",',
        },
        "pytest_commands": [
            ["tests/test_conditions.py::TestNormalizeCondition::test_reject_synonym", "-q"],
        ],
        "expected_rationale": "reject synonym should remain strictly greater-than.",
    },
    {
        "id": "M002_conditions_approve_lte_to_lt",
        "target_file": "src/conditions.py",
        "description": "Flip approve threshold operator from <= to <",
        "mutation_type": "dsl_operator_flip",
        "apply_rule": {
            "kind": "replace_one",
            "old": '"approve":          "amount <= 5000",',
            "new": '"approve":          "amount < 5000",',
        },
        "pytest_commands": [
            ["tests/test_conditions.py::TestNormalizeCondition::test_approve_synonym", "-q"],
        ],
        "expected_rationale": "approve synonym must include the 5000 boundary.",
    },
    {
        "id": "M003_conditions_has_po_synonym_flip",
        "target_file": "src/conditions.py",
        "description": "Perturb HAS_PO synonym to incorrect canonical form",
        "mutation_type": "synonym_map_perturbation",
        "apply_rule": {
            "kind": "replace_one",
            "old": '"HAS_PO":           "has_po == true",',
            "new": '"HAS_PO":           "has_po == false",',
        },
        "pytest_commands": [
            ["tests/test_conditions.py::TestNormalizeCondition::test_HAS_PO_synonym", "-q"],
        ],
        "expected_rationale": "HAS_PO must map to has_po == true.",
    },
    {
        "id": "M004_conditions_and_to_or",
        "target_file": "src/conditions.py",
        "description": "Weaken conjunction by evaluating with any() instead of all()",
        "mutation_type": "conjunction_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "return all(p(state) for p in sub_preds)",
            "new": "return any(p(state) for p in sub_preds)",
        },
        "pytest_commands": [
            ["tests/test_conditions.py::TestCompileCondition::test_conjunction_first_false", "-q"],
            ["tests/test_conditions.py::TestCompileCondition::test_conjunction_second_false", "-q"],
        ],
        "expected_rationale": "AND chains must fail when any conjunct is false.",
    },
    {
        "id": "M005_router_conditional_cardinality_weakened",
        "target_file": "src/agent/router.py",
        "description": "Treat multiple conditional matches as a single match",
        "mutation_type": "router_fail_closed_mutation",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if len(cond_matches) == 1:",
            "new": "    if len(cond_matches) >= 1:",
        },
        "pytest_commands": [
            ["tests/test_router_audit.py::TestAmbiguousRoute::test_ambiguous_route", "-q"],
        ],
        "expected_rationale": "2+ conditional matches must fail-closed as ambiguous_route.",
    },
    {
        "id": "M006_router_unconditional_cardinality_weakened",
        "target_file": "src/agent/router.py",
        "description": "Treat multiple unconditional edges as single fallback",
        "mutation_type": "router_fail_closed_mutation",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if len(unconditional) == 1:",
            "new": "    if len(unconditional) >= 1:",
        },
        "pytest_commands": [
            [
                "tests/test_router_fail_closed.py::TestAmbiguousRoute::"
                "test_multiple_unconditional_routes_to_station",
                "-q",
            ],
        ],
        "expected_rationale": "multiple unconditional edges must route to ambiguous station.",
    },
    {
        "id": "M007_router_unconditional_reason_relabel",
        "target_file": "src/agent/router.py",
        "description": "Relabel unconditional fallback reason incorrectly",
        "mutation_type": "router_observability_mutation",
        "apply_rule": {
            "kind": "replace_one",
            "old": '            reason="unconditional_fallback",',
            "new": '            reason="condition_match",',
        },
        "pytest_commands": [
            [
                "tests/test_router_audit.py::TestUnconditionalFallback::"
                "test_unconditional_fallback",
                "-q",
            ],
        ],
        "expected_rationale": "router reason codes are part of deterministic contract.",
    },
    {
        "id": "M008_router_station_guard_inverted",
        "target_file": "src/agent/router.py",
        "description": "Invert station_map guard in exception path",
        "mutation_type": "router_fail_closed_mutation",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if station_map is not None:",
            "new": "    if station_map is None:",
        },
        "pytest_commands": [
            ["tests/test_router_fail_closed.py::TestNoRoute::test_no_match_routes_to_station", "-q"],
        ],
        "expected_rationale": "when station_map is provided, no_route must resolve to station.",
    },
    {
        "id": "M009_verifier_amount_tolerance_weakened",
        "target_file": "src/verifier.py",
        "description": "Relax amount mismatch tolerance far beyond expected bound",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if delta > 0.01:\n        codes.append(\"AMOUNT_MISMATCH\")",
            "new": "    if delta > 1000.0:\n        codes.append(\"AMOUNT_MISMATCH\")",
        },
        "pytest_commands": [
            ["tests/test_verifier.py::TestAmountMismatch::test_value_100_evidence_50", "-q"],
        ],
        "expected_rationale": "material amount mismatches must be rejected.",
    },
    {
        "id": "M010_verifier_po_branch_inverted",
        "target_file": "src/verifier.py",
        "description": "Invert has_po branch that enforces PO pattern evidence",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if value is True:",
            "new": "    if value is False:",
        },
        "pytest_commands": [
            ["tests/test_verifier.py::TestPOPatternMissing::test_has_po_true_but_no_po_pattern", "-q"],
        ],
        "expected_rationale": "has_po=True without PO evidence pattern must fail.",
    },
    {
        "id": "M011_verifier_disambiguation_pick_first",
        "target_file": "src/verifier.py",
        "description": "Accept ambiguous amount evidence by picking first candidate",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if len(candidates) == 1:",
            "new": "    if len(candidates) >= 1:",
        },
        "pytest_commands": [
            ["tests/test_verifier.py::TestAmountAmbiguousFail::test_no_keyword_near_any_number", "-q"],
            ["tests/test_verifier.py::TestAmountAmbiguousFail::test_multiple_keywords_multiple_candidates_rejected", "-q"],
        ],
        "expected_rationale": "ambiguous multi-number evidence must not be auto-accepted.",
    },
    {
        "id": "M012_verifier_keyword_window_shrunk",
        "target_file": "src/verifier.py",
        "description": "Shrink keyword lookback window, breaking valid disambiguation",
        "mutation_type": "verifier_regression",
        "apply_rule": {
            "kind": "replace_one",
            "old": "_KEYWORD_WINDOW = 30",
            "new": "_KEYWORD_WINDOW = 3",
        },
        "pytest_commands": [
            ["tests/test_verifier.py::TestAmountDisambiguation::test_keyword_in_window_passes", "-q"],
            ["tests/test_verifier.py::TestAmountDisambiguation::test_keyword_beyond_3_chars_within_30_passes", "-q"],
        ],
        "expected_rationale": "keyword-guided disambiguation should pass for canonical evidence.",
    },
    {
        "id": "M013_linter_gateway_null_guard_inverted",
        "target_file": "src/linter.py",
        "description": "Invert gateway null-condition guard",
        "mutation_type": "linter_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "            if raw_cond is None:",
            "new": "            if raw_cond is not None:",
        },
        "pytest_commands": [
            [
                "tests/test_linter.py::TestGatewaySemantics::"
                "test_gateway_null_condition_is_error",
                "-q",
            ],
        ],
        "expected_rationale": "gateway edges with null conditions must raise lint errors.",
    },
    {
        "id": "M014_linter_fanout_duplicate_guard_inverted",
        "target_file": "src/linter.py",
        "description": "Invert duplicate normalized-condition fanout check",
        "mutation_type": "linter_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "            if norm in seen_norm:",
            "new": "            if norm not in seen_norm:",
        },
        "pytest_commands": [
            [
                "tests/test_linter.py::TestGatewaySemantics::"
                "test_gateway_fanout_same_condition_from_fixture",
                "-q",
            ],
        ],
        "expected_rationale": "same-condition fanout must be detected as an error.",
    },
    {
        "id": "M015_invariants_placeholder_guard_inverted",
        "target_file": "src/invariants.py",
        "description": "Invert placeholder-condition invariant guard",
        "mutation_type": "invariant_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "        if raw_stripped.upper() in _PLACEHOLDER_CONDITIONS:",
            "new": "        if raw_stripped.upper() not in _PLACEHOLDER_CONDITIONS:",
        },
        "pytest_commands": [
            ["tests/test_linter.py::TestPlaceholderCondition::test_if_condition_on_edge", "-q"],
            ["tests/test_linter.py::TestPlaceholderCondition::test_approve_placeholder_detected_by_invariant_directly", "-q"],
        ],
        "expected_rationale": "placeholder conditions must always trigger lint errors.",
    },
    {
        "id": "M016_invariants_match_router_guard_inverted",
        "target_file": "src/invariants.py",
        "description": "Invert match_result router ownership guard",
        "mutation_type": "invariant_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "        if frm in match_decision_ids:",
            "new": "        if frm not in match_decision_ids:",
        },
        "pytest_commands": [
            [
                "tests/test_linter.py::TestMatchResultRouting::"
                "test_task_routing_on_match_result_is_error",
                "-q",
            ],
            [
                "tests/test_linter.py::TestMatchResultRouting::"
                "test_task_match_result_no_match_decision_gateways",
                "-q",
            ],
        ],
        "expected_rationale": "only MATCH_DECISION gateways may route on match_result.",
    },
    # ------------------------------------------------------------------
    # Date validator mutants (RFC 6C)
    # ------------------------------------------------------------------
    {
        "id": "M017_date_eu_disambiguation_inverted",
        "target_file": "src/verifier.py",
        "description": "Swap EU branch guard from second <= 12 to second >= 12",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "if first > 12 and second <= 12:",
            "new": "if first > 12 and second >= 12:",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_invoice_date_eu_format_day_gt_month", "-q"],
        ],
        "expected_rationale": (
            "EU date 25/06/2025 (first=25 > 12, second=6 < 12) exercises the mutated branch; "
            "mutant changes <= to >= causing second=6 to fail the guard, producing DATE_AMBIGUOUS."
        ),
    },
    {
        "id": "M018_date_equal_pair_branch_inverted",
        "target_file": "src/verifier.py",
        "description": "Flip equal-pair guard from == to !=",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "elif first == second:",
            "new": "elif first != second:",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_invoice_date_ambiguous_fails_explicitly", "-q"],
        ],
        "expected_rationale": (
            "03/04/2025 (first != second, both <= 12) should be DATE_AMBIGUOUS "
            "but mutant would match the elif branch."
        ),
    },
    {
        "id": "M019_date_ambiguous_flag_inverted",
        "target_file": "src/verifier.py",
        "description": "Invert ambiguous propagation: saw_ambiguous to not saw_ambiguous",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "if saw_ambiguous:",
            "new": "if not saw_ambiguous:",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_invoice_date_ambiguous_fails_explicitly", "-q"],
            ["tests/test_verifier_field_expansion.py::test_invoice_date_us_format_normalizes_to_iso", "-q"],
        ],
        "expected_rationale": (
            "Ambiguous flag inversion would suppress DATE_AMBIGUOUS on "
            "03/04/2025 and falsely fire on unambiguous evidence."
        ),
    },
    {
        "id": "M020_date_ambiguous_path_bypassed",
        "target_file": "src/verifier.py",
        "description": "Change DATE_AMBIGUOUS return to DATE_PARSE_FAILED in both-<=12 else branch",
        "mutation_type": "verifier_regression",
        "apply_rule": {
            "kind": "replace_one",
            "old": "        # Both <= 12; cannot disambiguate\n        return None, \"DATE_AMBIGUOUS\"",
            "new": "        # Both <= 12; cannot disambiguate\n        return None, \"DATE_PARSE_FAILED\"",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_invoice_date_ambiguous_fails_explicitly", "-q"],
        ],
        "expected_rationale": "Ambiguous dates must return DATE_AMBIGUOUS, not DATE_PARSE_FAILED.",
    },
    # ------------------------------------------------------------------
    # Tax validator mutants (RFC 6C)
    # ------------------------------------------------------------------
    {
        "id": "M021_tax_anchor_guard_inverted",
        "target_file": "src/verifier.py",
        "description": "Invert anchor requirement: not search -> search",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "if not _TAX_ANCHOR_RE.search(evidence):",
            "new": "if _TAX_ANCHOR_RE.search(evidence):",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_tax_anchor_disambiguates_from_subtotal_shipping_total", "-q"],
        ],
        "expected_rationale": (
            "Evidence 'Tax: 35.00' has anchor; inverting would return TAX_ANCHOR_MISSING."
        ),
    },
    {
        "id": "M022_tax_ambiguity_guard_weakened",
        "target_file": "src/verifier.py",
        "description": "Suppress multi-value rejection: > 1 -> > 100",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "if len(unique_values) > 1:\n        return None, \"TAX_AMBIGUOUS_EVIDENCE\"",
            "new": "if len(unique_values) > 100:\n        return None, \"TAX_AMBIGUOUS_EVIDENCE\"",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_tax_multiple_anchored_values_rejected", "-q"],
        ],
        "expected_rationale": "Two different tax-anchor values must be rejected as TAX_AMBIGUOUS_EVIDENCE.",
    },
    {
        "id": "M023_tax_tolerance_weakened",
        "target_file": "src/verifier.py",
        "description": "Weaken tax mismatch check: delta > 0.01 -> delta > 1000.0",
        "mutation_type": "verifier_weakening",
        "apply_rule": {
            "kind": "replace_one",
            "old": "    if delta > 0.01:\n        codes.append(\"TAX_AMOUNT_MISMATCH\")",
            "new": "    if delta > 1000.0:\n        codes.append(\"TAX_AMOUNT_MISMATCH\")",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_tax_amount_value_mismatch", "-q"],
        ],
        "expected_rationale": "Material tax amount mismatches must be rejected.",
    },
    {
        "id": "M024_tax_anchor_window_expanded",
        "target_file": "src/verifier.py",
        "description": "Expand anchor proximity window: {0,24} -> {0,240}",
        "mutation_type": "verifier_regression",
        "apply_rule": {
            "kind": "replace_one",
            "old": "[^0-9\\-]{0,24}",
            "new": "[^0-9\\-]{0,240}",
        },
        "pytest_commands": [
            ["tests/test_verifier_field_expansion.py::test_tax_distant_number_not_captured", "-q"],
        ],
        "expected_rationale": (
            "Distant numbers (>24 chars from tax anchor) must not be captured as tax values."
        ),
    },
]

