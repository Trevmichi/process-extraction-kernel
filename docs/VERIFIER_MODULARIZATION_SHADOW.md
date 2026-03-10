# Verifier Modularization (RFC 3) - Shadow Mode Plan

## Why Modularize
The current verifier is reliable but monolithic. A registry-based structure will:
- isolate field-specific logic behind explicit interfaces,
- make per-field ownership and extension safer,
- support targeted regression checks per field validator.

## Key Risks
- Edge-case nuance loss during abstraction (especially `has_po` and amount disambiguation).
- Abstraction leaks where generic interfaces cannot express field-specific invariants.
- Silent behavior drift if modular path diverges from legacy path before cutover.

## Proposed Interfaces
Phase 1 introduces additive scaffolding only:
- `FieldValidatorSpec`:
  - `field_name`
  - `validator(extraction, norm_raw, codes, provenance)`
  - `description`
- `FieldValidatorRegistry`:
  - ordered execution (`ordered_specs()`)
  - lookup (`get(field_name)`)
  - deterministic field list (`field_names()`)
- Legacy adapters:
  - `validate_vendor_via_legacy`
  - `validate_amount_via_legacy`
  - `validate_has_po_via_legacy`

These adapters wrap existing legacy field validators directly, preserving semantics.

## Shadow-Mode Strategy
No production cutover in this phase.

Shadow helper flow:
1. Run legacy `verify_extraction(...)` (source of truth).
2. Run registry-backed path using legacy adapters.
3. Compare outputs and emit structured diff:
   - validity boolean
   - failure code sequence
   - provenance top-level key compatibility and value mismatches

The shadow helper is opt-in utility code and is not wired into production routing.

## Cutover Status — COMPLETE

All cutover criteria met and cutover executed:
1. **Zero diffs across 135 shadow fixtures** (17 unit + 118 gold invoices) — `tests/test_verifier_cutover_baseline.py`.
2. **Zero diffs across eval harness** — 59 tests passing post-cutover.
3. **Mutation harness** — 4/4 verifier mutants killed post-cutover.
4. **Full suite** — 1060 tests passing, no regressions.

`verify_extraction()` in `src/verifier.py` now uses `build_legacy_validator_registry()` and iterates `registry.ordered_specs()` instead of direct `_verify_*` calls. Public signature is unchanged. The `_verify_vendor`, `_verify_amount`, and `_verify_has_po` functions remain in `verifier.py` and are called by the legacy adapter wrappers in `verifier_registry.py`.

## Rollback Strategy
Single-file rollback: restore the 3 direct `_verify_*` calls in `verify_extraction()` body and remove the `build_legacy_validator_registry` import. The registry and shadow modules are additive and remain in place regardless.

```bash
git checkout -- src/verifier.py
```

## Batch Shadow Validation Utility
Use `scripts/run_verifier_shadow_batch.py` to compare legacy vs registry outputs
over many cases and generate cutover-ready diff summaries.

### Quick examples
Compare a small sample from eval gold records:

```bash
python scripts/run_verifier_shadow_batch.py \
  --expected-jsonl datasets/expected.jsonl \
  --datasets-dir datasets \
  --limit 20
```

Compare explicit JSON case file(s):

```bash
python scripts/run_verifier_shadow_batch.py \
  --input-json data/shadow_cases.json
```

Emit machine-readable report:

```bash
python scripts/run_verifier_shadow_batch.py \
  --expected-jsonl datasets/expected.jsonl \
  --limit 50 \
  --json-out outputs/verifier_shadow_report.json
```

Focus on actionable diffs:

```bash
python scripts/run_verifier_shadow_batch.py \
  --expected-jsonl datasets/expected.jsonl \
  --only-diffs \
  --diff-type codes \
  --max-diffs 25 \
  --json-out outputs/verifier_shadow_codes_diff.json
```

### Summary fields
The batch report includes stable summary counters:
- `total_compared`
- `no_diff`
- `diff_valid_flag`
- `diff_codes`
- `diff_provenance`
- `diff_values`
- `error`

