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
            "old": "    if delta > 0.01:",
            "new": "    if delta > 1000.0:",
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
]

