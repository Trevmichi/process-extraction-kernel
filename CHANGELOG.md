# Changelog

All entries are grounded in commits from `docs/_git_log_stat.txt`.

---

## 2026-03-09 -- Phases 10a-d + Eval Stratification

- **Policy abstraction (Phase 10c)**: introduced `src/policy.py` with frozen
  `PolicyConfig` dataclass centralizing `approval_threshold`, `po_mode`,
  `required_fields`, and exception station intents. All consumers
  (`ontology.py`, `contracts.py`, `router.py`, `verifier.py`, `patch_logic.py`,
  `eval_runner.py`) redirected from scattered constants to the policy singleton.
  ([commit b5351f7])

- **Schema validation gates (Phase 10a)**: added `src/schema_validator.py` for
  runtime JSON Schema validation at extraction emission points. Rejects
  payloads with unexpected fields before they reach the verifier.
  ([commit b5351f7])

- **Evidence quality tiers (Phase 10b)**: introduced `MatchTier` literal type
  (`exact_match`, `normalized_match`, `not_found`) in `contracts.py`. All 5
  field verifiers classify match quality; tiers propagate through provenance
  and verifier summary audit events.
  ([commit b5351f7])

- **invoice_date and tax_amount activation (Phase 10d)**: wired the already-built
  date and tax validators into the live extraction pipeline. Extraction prompts
  expanded from 3 to 5 fields with active-but-optional semantics. State
  promotion inside `if valid:` only. Verifier summary includes optional field
  sub-dicts when verifier processes them. Extended fields eval bucket improved
  from 15% to 27.5% field accuracy.
  ([commit 031ffda])

- **Eval stratification (Phase 11)**: stratified benchmark reporting by
  scenario bucket (`clean_standard`, `noisy_ocr_synthetic`, `match_path`,
  `extended_fields`). Per-bucket terminal and field accuracy in eval reports.
  ([commit 960a79b])

- **Shared validation pipeline**: extracted `_validate_extraction_pipeline` and
  `_build_verifier_summary` from ENTER_RECORD/CRITIC_RETRY, eliminating ~150
  lines of duplication.
  ([commit 73a9fc6])

- **Test infrastructure**: added `tests/conftest.py` with shared fixtures;
  removed `sys.path` boilerplate from 27 test files. Documented policy
  import-time caching semantics.
  ([commit a5f854b])

---

## 2026-03-07 -- Arithmetic + Operator Surfaces + README

- **Arithmetic consistency layer (Phase 8)**: added `src/arithmetic.py` with
  two pure source-text cross-checks (`total_sum`, `tax_rate`). Closest-keyword-wins
  classifier, tolerance-based delta comparison. `ARITH_TOTAL_MISMATCH` and
  `ARITH_TAX_RATE_MISMATCH` failure codes integrated into both ENTER_RECORD
  and CRITIC_RETRY paths.
  ([commit e65077c])

- **Operator review panel**: synthesis of primary issue, supporting signals,
  and review focus for non-success outcomes. Failure drill-down with
  surface-specific structured detail rows.
  ([commit 0bb035f], [commit e61dd76])

- **App typed audit display**: per-entry formatted display with icons and tags
  for 14 entry types. Session history sidebar with outcome-based summary
  column.
  ([commit 7322b99])

- **Arithmetic and routing audit schemas**: added `audit_event_arithmetic_check_v1`
  and `audit_event_route_record_v1` JSON Schemas.
  ([commit a76aca0])

- **README update**: comprehensive rewrite covering architecture, repo structure,
  evaluation, schema contracts, and operator surfaces.
  ([commit 956a7c5])

---

## 2026-03-06 -- Schemas, Audit Parser, Explanation Layer

- **JSON Schema artifacts (Phase 7)**: 14 Draft 2020-12 schemas in `schema/`.
  Data contracts: `extraction_payload_v1`, `provenance_report_v1`,
  `failure_codes_v1`, `route_record_v1`, `gold_record_v1`. Audit events:
  `extraction`, `exception_station`, `match_result_set`, `route_decision`,
  `verifier_summary`, `critic_retry`. All enforce `additionalProperties: false`.
  93 tests in `test_schemas.py`.
  ([commit b744021] through [commit 4f92912])

- **Canonical audit parser**: `src/audit_parser.py` — single-pass forward
  parser producing 14 frozen dataclass entry types in an immutable
  `ParsedAuditLog`. Defensive: never raises on malformed input.
  ([commit 50234cb], [commit f25f1f7])

- **ExplanationReport**: `src/explanation.py` — transforms `ParsedAuditLog`
  into a 9-component structured report with `OutcomeClassification` (always
  present) and 6 optional components. All dataclasses frozen with `.to_dict()`.
  Integrated into `app.py` for exception, status, verifier, and match display.
  ([commit 789d8a9], [commit ee194b3], [commit d3afe56])

- **Ontology freeze**: `StatusType`, `ActionType`, `DecisionType` as runtime
  `frozenset`s derived from `Literal` annotations. Closed `MISSING_DATA` and
  `NEEDS_RETRY` gaps.
  ([commit b7b037b])

- **Data contracts**: `ExtractionPayload` and `ProvenanceReport` TypedDicts in
  `src/contracts.py` with structural validation. `STRUCT_*` failure codes for
  malformed LLM responses (before verifier).
  ([commit a2fff43], [commit 872aa11])

---

## 2026-03-05 -- Router Observability, Verifier Registry, Extended Fields

- **RouteRecord observability (RFC 1)**: frozen `RouteRecord` dataclass in
  `src/agent/router.py` — full routing trace per gateway decision.
  Deterministically sorted fields, JSON-serializable, emitted as audit events.
  ([commit a80914a])

- **Verifier registry**: `src/verifier_registry.py` — registry-backed field
  validation with zero-diff cutover from inline logic. Shadow comparison runner
  for safe migration validation. Batch shadow runner + curated mutation harness.
  ([commit 3020338], [commit 6a9dc62], [commit e8d9eec], [commit b0ecd98])

- **invoice_date and tax_amount validators (RFC 6A-C)**: deterministic
  validators for both fields (`DATE_*`, `TAX_*` failure codes). Dataset/eval
  scaffolding for extended fields. Mutation catalog + runner infrastructure.
  ([commit 19999ba], [commit 295e2f0], [commit 75adc52])

- **Condition diagnostics**: added provenance and type validation helpers to
  `src/conditions.py`.
  ([commit d4e80d1])

- **Quality gates documentation**: deterministic validation sequences, PR
  checklist, mutation guidance, failure-pattern taxonomy.
  ([commit 7929a7c])

---

## 2026-03-04 -- Auto-Optimizer, Auto-Refactor, Dataset Expansion

- **Auto-optimizer meta-agent**: autonomous triage → Gemini patch → test →
  PR pipeline. Added sweep mode, timeouts, retry logic, and headless safety
  rails.
  ([commit 1739138], [commit b3d3e76], [commit 7e255d8])

- **Auto-refactor**: strict typing and docstrings across ~30 modules via
  Codex-driven refactoring.
  ([commits 2a87150 through c027e0a])

- **Auto-test coverage**: adversarial invoice fixtures,
  `PO_PATTERN_MISSING`, OCR noise edge cases, `AMBIGUOUS_AMOUNT_EVIDENCE`,
  and `both_terminal_and_field_mismatch` coverage.
  ([commit 609689a] through [commit c1f5f4e])

- **Git hygiene**: removed 6,919 tracked `.venv/` and `__pycache__/` files
  from the index.
  ([commit 7d4053a])

---

## 2026-03-03 -- Correctness Hardening + Eval Harness

- **Condition DSL AND extension**: extended grammar to support
  `comparison (AND comparison)*`; guarded the n3 `has_po == false` edge with
  `status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false`,
  resolving AMBIGUOUS_ROUTE when extraction fails on no-PO invoices.
  ([commit 6a697e4])

- **Gold invoice dataset + eval harness**: 30 gold invoices across 5 vendors
  and 3 scenarios, with `eval_runner.py` supporting mock and live modes.
  Achieves 30/30 terminal accuracy and 90/90 field accuracy.
  ([commit 1c13717])

- **Stability hardening**: verifier PO regex fix, router audit logging,
  normalizer and linter improvements, state schema formalization.
  ([commit 6c46331])

- **Invariants, conditions, linter, normalizer, verifier**: introduced
  `src/conditions.py` (eval-free condition DSL), `src/linter.py` (graph
  validation), `src/invariants.py` (structural checks),
  `src/normalize_graph.py` (15 idempotent repair passes), and
  `src/verifier.py` (evidence-backed extraction validation). Added 600+
  tests.
  ([commit 021913e])

- **Added .gitignore entries** for generated eval outputs and runtime routing
  logs.
  ([commit c7b2df9])

---

## 2026-03-01 -- v1.0 Release

- **LangGraph agent integration**: created `src/agent/` module with compiler,
  nodes, router, and state. Added Streamlit UI (`app.py`), batch runner
  (`batch_runner.py`), CLI runner (`run_agent.py`), and dynamic logic
  patching (`patch_logic.py`). Tagged as v1.0.
  ([commit d3b89df])

- **Production extraction finalization**: gap analysis reporting, benchmarker,
  schema suggestions, README update.
  ([commit 50427e6])

- **Agent node improvements**: minor fixes to `src/agent/nodes.py`.
  ([commit a184fec])

---

## 2026-02-28 -- Initial Development

- **Project initialization**: `.gitignore`, README, data collection and
  analysis infrastructure.
  ([commit ee3deff], [commit b2e5507], [commit 47bf86f])

- **Rapid prototyping**: heuristic extraction engine (`src/heuristic.py`),
  canonical ontology (`src/ontology.py`), LLM classifier with self-healing
  recursive splitter (`src/llm_classifier.py`), 5 test documents.
  ([commit afbe25f] through [commit a05623a])
