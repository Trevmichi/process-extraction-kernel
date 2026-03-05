# Quality Gates & Contributor Workflow

Practical guide to maintaining deterministic quality in this repo.
Covers validation sequences, safety-mechanism selection, mutation harness usage,
and common failure patterns.

---

## 1. Quality Posture Snapshot

As of this document update: 921 tests passing, curated mutation score 16/16 killed.

| Layer | Status | Detail |
|-------|--------|--------|
| **Test suite** | 921 passing | `pytest -x` from project root |
| **Mutation harness** | 16/16 killed | Curated deterministic-layer catalog (conditions, router, verifier, linter/invariants) |
| **Eval harness** | Gold dataset + adversarial tags | Mock mode: `python eval_runner.py`; live mode: `python eval_runner.py --live` |
| **Router observability** | RouteRecord on every decision | `src/agent/router.py` — `build_route_record()` emits structured audit trail |
| **Graph linter** | 5 sections (A–E) | Referential integrity, actor/artifact, gateway semantics, decision consistency, structural invariants |
| **Condition DSL** | Diagnostics + provenance | `diagnose_condition()`, `validate_condition_types()` in `src/conditions.py` |

---

## 2. Validation Sequence by Change Type

### Condition DSL (`src/conditions.py`)

```bash
pytest -q tests/test_conditions.py
pytest -q tests/test_linter.py tests/test_router_audit.py
python scripts/run_mutation_smoke.py --category conditions
pytest -x
```

### Verifier (`src/verifier.py`)

```bash
pytest -q tests/test_verifier.py
python eval_runner.py                          # mock mode smoke
python scripts/run_mutation_smoke.py --category verifier
pytest -x
```

### Router (`src/agent/router.py`)

```bash
pytest -q tests/test_router_audit.py tests/test_router_fail_closed.py
pytest -q tests/test_batch_smoke.py
pytest -q tests/test_production_graph_regressions.py
python scripts/run_mutation_smoke.py --category router
pytest -x
```

### Linter / Invariants (`src/linter.py`, `src/invariants.py`)

```bash
pytest -q tests/test_linter.py
pytest -q tests/test_production_graph_regressions.py
python scripts/run_mutation_smoke.py --category linter_invariants
pytest -x
```

### Graph Normalization (`src/normalize_graph.py`, `patch_logic.py`)

```bash
pytest -q tests/test_normalize.py tests/test_patch.py tests/test_patch_exceptions.py
pytest -q tests/test_production_graph_regressions.py
pytest -x
```

### Datasets / Eval Fixtures (`datasets/`, `eval_runner.py`)

```bash
pytest -q tests/test_eval_harness.py
python eval_runner.py                          # mock mode
python eval_runner.py --show-failures          # inspect any regressions
```

---

## 3. Choosing the Right Safety Mechanism

| Mechanism | When to use | Example |
|-----------|------------|---------|
| **Unit test** | Default for any deterministic logic change. Test the contract, not the implementation. | `test_conjunction_first_false` verifies AND short-circuits correctly |
| **Gold fixture / adversarial tag** | When testing LLM extraction quality or evidence grounding against realistic invoice text. | `inv_042.txt` with `adversarial:amount_near_po` tag tests amount disambiguation near PO numbers |
| **Invariant / linter rule** | When enforcing a structural graph contract that must hold after normalization. | `check_match_result_routing()` ensures only MATCH_DECISION gateways route on `match_result` |
| **Mutation mutant** | When a boundary condition or guard clause needs regression protection beyond unit tests. | M011 proved that `len(candidates) == 1` boundary was untested on the `> 1` side |
| **RouteRecord assertion** | When validating routing decisions, reason codes, or audit trail completeness. | `test_unconditional_fallback` checks reason is `"unconditional_fallback"`, not `"condition_match"` |

### When mutation testing adds value beyond unit tests

The Phase 2 survivor triage (M011–M016) demonstrated that passing unit tests
do not guarantee boundary coverage. All 4 survivors had broad test suites that
passed — yet the mutants revealed:

- A test that exercised the wrong branch of a two-path detector (M015)
- A test that never reached the disambiguation function due to a fast path (M012)
- A test that checked only one side of a cardinality boundary (M011)
- A test whose fixture masked the real escape via false-positive errors (M016)

**Rule of thumb**: if your change involves a numeric boundary (`== 1`, `> 0.01`),
a guard clause (`if x in set`), or a mode switch (`if value is True`), consider
whether the mutation catalog should cover it.

---

## 4. Mutation Harness Quick Reference

Full documentation: [docs/MUTATION_TESTING.md](MUTATION_TESTING.md)

### Common commands

```bash
# Preview without mutating
python scripts/run_mutation_smoke.py --dry-run --max-mutants 5

# Run by category
python scripts/run_mutation_smoke.py --category verifier

# Run specific mutant(s)
python scripts/run_mutation_smoke.py \
  --mutant-id M011_verifier_disambiguation_pick_first \
  --mutant-id M012_verifier_keyword_window_shrunk

# List catalog
python scripts/run_mutation_smoke.py --list-mutants --list-format json

# Full run with JSON report
python scripts/run_mutation_smoke.py --json-out outputs/mutation_report.json
```

### Status meanings

| Status | Meaning |
|--------|---------|
| `killed` | At least one pytest command failed — mutant was caught |
| `survived` | All pytest commands passed — **investigate** (test gap or equivalent mutant) |
| `error` | Infrastructure issue (timeout, interpreter error) |
| `skipped` | Dry-run, patch mismatch, or missing target file |

### Key lesson from Phase 2

**Survived does not mean equivalent.** All 4 Phase 1 survivors turned out to be
genuine test gaps, not redundant or equivalent mutants. Always investigate before
classifying a survivor as acceptable.

---

## 5. PR Checklist for Deterministic-Layer Changes

- [ ] Targeted tests added or updated for changed code paths
- [ ] Mutation subset run for affected category (if deterministic layer)
- [ ] RouteRecord / diagnostics impact reviewed (if routing or DSL change)
- [ ] No semantic drift in router fail-closed behavior
- [ ] Linter and invariant rules still pass on production graph
- [ ] Documentation updated if adding new safety mechanisms

---

## 6. Common Failure-Pattern Taxonomy

Patterns identified during mutation survivor triage. Use these as a checklist
when reviewing tests for completeness.

### Wrong-path coverage

**What**: A test passes, but through a different detection path than the one
being validated. The intended path is actually broken.

**Example**: M015 — `check_no_placeholder_conditions()` has two detection paths:
(a) direct membership check and (b) normalize-to-None fallback. The test used
`"IF_CONDITION"` which normalizes to None, so path (b) caught it even when
path (a) was inverted by the mutation.

**Prevention**: Call the function under test directly with inputs that isolate
the specific path. Use inputs where only one detection path fires.

### Fast-path bypass

**What**: Production code has an early-exit optimization. The test only exercises
the fast path, never reaching the full logic.

**Example**: M012 — The verifier's `_verify_amount()` has a single-number fast
path (`len(numbers) == 1`) that skips `_disambiguate_amount()` entirely. The
test's evidence contained exactly one number, so shrinking `_KEYWORD_WINDOW`
from 30 to 3 had no effect.

**Prevention**: Ensure tests exist for both the optimized path and the
general-case path. For disambiguation: test with 1 number (fast path) and
2+ numbers (full disambiguation).

### Boundary completeness

**What**: A boundary check (e.g., `== 1`) is tested on only one side of the
boundary, missing the case where the condition flips.

**Example**: M011 — `if len(candidates) == 1` was tested with 0 candidates
(no keywords near numbers) but never with 2+ candidates. The mutation to
`>= 1` was invisible because both `== 1` and `>= 1` return None for 0.

**Prevention**: For every `== N` or `> N` boundary, write tests for at least:
N-1 (below), N (at), and N+1 (above).

### Redundant detection masking

**What**: Multiple detectors cover the same issue. A test relies on one
detector but passes because a different detector (or false positives from
valid data) satisfies the assertion.

**Example**: M016 — The test fixture included valid MATCH_DECISION edges that
produced false-positive `E_MATCH_RESULT_WRONG_ROUTER` errors when the guard
was inverted. The test's `"code" in codes` assertion passed from those false
positives, masking the fact that the invalid task edge was silently accepted.

**Prevention**: Test with minimal fixtures that exercise only the condition
under test. When checking for a specific error, verify it fires for the
correct input (e.g., check the error context, or use a graph with no other
sources of the same error code).
