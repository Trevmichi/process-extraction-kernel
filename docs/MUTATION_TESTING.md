# Mutation Testing (RFC 4, Phase 1)

## Purpose and Scope
This phase adds a mutation-testing scaffold for deterministic layers only:
- Condition DSL and normalization (`src/conditions.py`)
- Deterministic router/fail-closed behavior (`src/agent/router.py`)
- Evidence verifier (`src/verifier.py`)
- Linter and structural invariants (`src/linter.py`, `src/invariants.py`)

Out of scope in Phase 1:
- LLM generation behavior
- Broad randomized/generic mutation engines
- CI enforcement gates

## Why Curated, Domain-Specific Mutation
Generic mutation blasts create high noise and fragile mutants in this codebase.  
Phase 1 uses a curated catalog focused on known deterministic contracts:
- Operator boundaries (`==`, `!=`, `>`, `>=`, `<=`)
- Conjunction strictness (`AND` behavior)
- Synonym/canonical mapping correctness
- Router fail-closed semantics (`ambiguous_route`, `no_route`)
- Verifier strictness (PO evidence checks, amount mismatch checks)
- Linter/invariant enforcement guards

Goal: signal over volume.

## Result Categories
Each mutant run is classified as one of:
- `killed`: pytest command returned failing-test exit code (`1`)
- `survived`: all configured pytest commands passed (`0`)
- `error`: infrastructure/runtime issue (timeout, pytest usage error, etc.)
- `skipped`: mutant was not runnable (e.g., patch pattern mismatch, dry-run)

## Initial Mutation Budget
Phase 1 budget is intentionally small: **10-20 curated mutants**.  
Current catalog (`scripts/mutation_catalog.py`) ships with **16** mutants.

## Local Usage
### Quick Start
Run a non-destructive preview:

```bash
python scripts/run_mutation_smoke.py --dry-run --max-mutants 5
```

Then run a tiny real subset:

```bash
python scripts/run_mutation_smoke.py --max-mutants 2
```

### Command Examples
List catalog entries:

```bash
python scripts/run_mutation_smoke.py --list-mutants
```

List catalog entries as JSON:

```bash
python scripts/run_mutation_smoke.py --list-mutants --list-format json
```

Dry-run (no file mutation, no pytest execution):

```bash
python scripts/run_mutation_smoke.py --dry-run --max-mutants 5
```

Run the full curated smoke set:

```bash
python scripts/run_mutation_smoke.py
```

Run the first N mutants:

```bash
python scripts/run_mutation_smoke.py --max-mutants 3
```

Run one mutant by ID:

```bash
python scripts/run_mutation_smoke.py --mutant-id M005_router_conditional_cardinality_weakened
```

Run by category:

```bash
python scripts/run_mutation_smoke.py --category verifier --max-mutants 2
```

Run a subset and write JSON report:

```bash
python scripts/run_mutation_smoke.py \
  --mutant-id M005_router_conditional_cardinality_weakened \
  --mutant-id M006_router_unconditional_cardinality_weakened \
  --json-out outputs/mutation_smoke_report.json
```

Notes:
- The runner executes in a disposable temporary workspace copy.
- One mutant is applied at a time and the target file is restored after each run.
- Use `--python-executable <path>` if your project uses a non-default interpreter.
- Exit code is non-gating in this phase; inspect summary/report for outcomes.
- Categories are intentionally small and fixed in Phase 1:
  `conditions`, `router`, `verifier`, `linter_invariants`.

## Status Meanings
- `killed`: at least one configured pytest command failed (expected mutation catch).
- `survived`: all configured pytest commands passed under the mutation.
- `error`: runner/pytest infrastructure error (timeouts, interpreter issues, pytest runtime errors).
- `skipped`: mutant not run (dry-run, patch not applicable, missing target file, etc.).

## Phase 2 — Survivor Triage (RFC 4 Phase 2)

Phase 1 produced 12 killed / 4 survived. Phase 2 triaged each survivor
and added targeted tests to kill all 4. Final score: **16/16 killed**.

### Survivor Root Causes and Fixes

| Mutant | Root Cause | Fix |
|--------|-----------|-----|
| **M011** (verifier candidate count) | Targeted test had 0 candidates (no keywords near numbers); mutation only matters when candidates > 1 | Added `test_multiple_keywords_multiple_candidates_rejected` — 2 numbers both with keywords nearby |
| **M012** (verifier keyword window) | Targeted test evidence had 1 number; single-number fast path skips disambiguation entirely | Added `test_keyword_beyond_3_chars_within_30_passes` — 2 numbers, keyword 8 chars away (beyond 3, within 30) |
| **M015** (invariant placeholder guard) | Function has (a) membership check + (b) normalize-to-None fallback; targeted test used "IF_CONDITION" (normalizes to None), so (b) caught it even with (a) inverted | Added `test_approve_placeholder_detected_by_invariant_directly` — calls invariant directly with "APPROVE" which normalizes to a valid expression (not None), isolating path (a) |
| **M016** (invariant match_result guard) | Test fixture included valid MATCH_DECISION edges that produced false-positive errors when guard inverted, masking the real escape | Added `test_task_match_result_no_match_decision_gateways` — calls invariant directly with no MATCH_DECISION gateways, isolating the guard |

### Patterns Identified

1. **Wrong-path coverage**: Tests can pass for the wrong reason when the code
   under test has redundant detection paths (M015) or when fixtures produce
   masking false positives (M016).
2. **Fast-path bypass**: When production code has early-exit optimizations
   (single-number fast path in verifier), tests must exercise the
   non-optimized path to validate the full logic (M012).
3. **Boundary completeness**: Boundary checks (== 1 vs >= 1) need tests on
   both sides of the boundary, not just one (M011).

## Future Phases
Planned expansion after Phase 2:
1. Nightly/CI integration with non-blocking trend reporting.
2. Expanded curated catalog with tighter per-module coverage targets.
3. Optional policy thresholds (e.g., max survived count) once stability is proven.
4. Better historical reporting and mutant drift detection across refactors.
