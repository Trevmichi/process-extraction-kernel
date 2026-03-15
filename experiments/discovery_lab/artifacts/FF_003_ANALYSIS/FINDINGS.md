# FF-003 Extended-Field Analysis — Findings

## Purpose

Identify the specific failure code(s) blocking each of the 6 FF-003 cases (INV-1070 through INV-1075), and explain why INV-1076 passes. All 7 records include `invoice_date` and `tax_amount` in expected_fields. The taxonomy currently classifies FF-003 as L3 (evidence-binding) with hypothesized failure codes. This analysis confirms or refutes those hypotheses.

## Method

1. For each of the 7 INV-107x records, run all 5 validation steps individually
2. Extract per-field diagnostic detail from verifier provenance (invoice_date, tax_amount)
3. Identify the first blocker in pipeline order for each case
4. Group cases by dominant failure code to identify sub-patterns
5. Compare failing cases against INV-1076 (the positive control)

## Results

| Invoice | Role | Date | Date Code | Tax | Tax Code | Arith | First Blocker |
|---------|------|------|-----------|-----|----------|-------|---------------|
| INV-1070 | FF-003 | FAIL | DATE_AMBIGUOUS | PASS | — | PASS | verifier |
| INV-1071 | FF-003 | PASS | — | FAIL | TAX_AMOUNT_MISMATCH | FAIL | verifier |
| INV-1072 | FF-003 | PASS | — | FAIL | TAX_AMOUNT_MISMATCH | FAIL | verifier |
| INV-1073 | FF-003 | FAIL | DATE_AMBIGUOUS | PASS | — | PASS | verifier |
| INV-1074 | FF-003 | PASS | — | PASS | — | FAIL | arithmetic |
| INV-1075 | FF-003 | FAIL | DATE_AMBIGUOUS | PASS | — | PASS | verifier |
| INV-1076 | Control | PASS | — | PASS | — | PASS | none |

## Per-field accuracy (across all 7 records)

- **invoice_date**: 4/7 pass (57.1%)
- **tax_amount**: 5/7 pass (71.4%)

## Observed sub-patterns

### ARITH_TOTAL_MISMATCH (1 case)

Cases: INV-1074

These cases pass the verifier (all field-level checks succeed) but fail the arithmetic check (`check_arithmetic`). The raw invoice text contains line items that do not sum to the stated total.

- **INV-1074**: verifier=PASS, arithmetic codes=['ARITH_TOTAL_MISMATCH']

> **Reclassification note**: These cases pass the L3 evidence-binding verifier. Their blocker is L1 input-text arithmetic, which overlaps with FF-001. Consider whether they should remain in FF-003 or be reclassified.

### DATE_AMBIGUOUS (3 cases)

Cases: INV-1070, INV-1073, INV-1075

The verifier's date parser (`_parse_date_token`) cannot disambiguate slash-delimited dates where both components are ≤ 12 (e.g., MM/DD vs DD/MM). Observed date evidence for these cases:

- **INV-1070**: value=`2026-12-03`, evidence=`Date: 12/03/2026`
- **INV-1073**: value=`2026-03-10`, evidence=`Date: 03/10/2026`
- **INV-1075**: value=`2026-09-08`, evidence=`Date: 09/08/2026`

### TAX_AMOUNT_MISMATCH (2 cases)

Cases: INV-1071, INV-1072

The verifier's tax parser (`_TAX_ANCHOR_VALUE_RE`) captures the first number after a tax/vat/gst anchor within 24 non-digit characters. When the evidence contains an embedded percentage (e.g., "VAT (19%)"), the regex captures the percentage rather than the actual tax amount. Observed tax evidence for these cases:

- **INV-1071**: value=`699.2`, evidence=`VAT (19%): EUR 699.20`, parsed=`19.0`, delta=`680.2`
- **INV-1072**: value=`1369.2`, evidence=`VAT (21%): EUR 1,369.20`, parsed=`21.0`, delta=`1348.2`

## Control case: INV-1076

- **Passes full pipeline**: True
- **Date**: pass=True, value=`2026-02-14`, evidence=`Invoice Date: 14/02/2026`, normalized=`2026-02-14`
- **Tax**: pass=True, value=`0.0`, evidence=`VAT: EUR 0.00`, parsed=`0.0`
- **Arithmetic**: pass=True
- **Tags**: ['tax_zero_explicit', 'happy_path', 'under_threshold', 'vendor_metrotech']

INV-1076 is the only INV-107x record that passes all validation gates. Comparing its field values against the failing cases reveals what differentiates it.

## Reclassification candidates

Cases: INV-1074

These cases pass the verifier but fail arithmetic (ARITH_TOTAL_MISMATCH). They may overlap with FF-001/L1 rather than belonging to FF-003/L3.

## First-blocker distribution (FF-003 targets only)

- **arithmetic**: 1
- **verifier**: 5

## Recommended next actions

These are descriptive recommendations based on the observed failure modes. No rescue implementation or production code changes are proposed.

1. **DATE_AMBIGUOUS** (3 cases): Consider a date disambiguation strategy — e.g., require ISO format in extraction prompts, or use document-level locale hints to resolve MM/DD vs DD/MM ambiguity.
2. **TAX_AMOUNT_MISMATCH** (2 cases): The `_TAX_ANCHOR_VALUE_RE` regex captures the first number after the anchor keyword. When the evidence contains an embedded percentage, this is the percentage rather than the tax amount. A regex improvement or extraction prompt change could address this.
3. **ARITH_TOTAL_MISMATCH** (1 cases): These cases pass the verifier but fail arithmetic. Assess whether they should be reclassified to FF-001/L1 (input-text arithmetic corruption).
4. **Dataset expansion**: The current FF-003 population (7 records) is too small for reliable rescue policy design. Expand the gold dataset with more `invoice_date` + `tax_amount` test cases before designing any intervention.

## Limitations

- This trace runs validators in isolation, not through the full graph. Graph-level routing behavior is inferred, not directly observed.
- N=7 (6 targets + 1 control) — small sample, interpret cautiously.
- All records use mock_extractions. Real LLM extraction may produce different evidence strings and different failure profiles.

