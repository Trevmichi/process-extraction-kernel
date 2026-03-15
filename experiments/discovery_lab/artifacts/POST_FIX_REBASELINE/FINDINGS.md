# Post-Fix Rebaseline — Findings

## Summary

After the FF-002 fixture correction (2026-03-15), the blocked cohort dropped from 25 to 20 cases (15.9% of 126 gold records). The FF-003 extended-field analysis then confirmed the failure mechanisms for the leading remaining family.

## Pre-Fix vs Post-Fix

| Metric | Pre-Fix | Post-Fix | Delta |
|--------|---------|----------|-------|
| Total blocked | 25 | 20 | -5 |
| Blocked rate | 19.8% | 15.9% | -3.9pp |
| Reachable | 101 | 106 | +5 |
| Active families | 4 | 3 | -1 (FF-002 resolved) |

The 5 unblocked cases (INV-2005, INV-2021, INV-2026, INV-2038, INV-2041) now reach `EXCEPTION_NO_PO` — their expected status.

## Family Distribution (Post-Fix)

| Family | Count | % of Blocked | Layer | Priority | Status |
|--------|-------|-------------|-------|----------|--------|
| FF-001 | 12 | 60% | L1 input-text | low | deferred (synthetic data fix) |
| FF-003 | 6 | 30% | L3 evidence-binding | medium | **analyzed** |
| FF-004 | 2 | 10% | L2 extraction-proposal | low | deferred (manual inspection) |
| FF-002 | 0 | — | eval fixture | resolved | fixture patched |

## Leading Target: FF-003

FF-003 is the leading production-relevant target. The FF-003 analysis (`ff003_analysis_20260315T141329Z`) confirmed 3 distinct failure sub-modes:

### DATE_AMBIGUOUS (3 cases: INV-1070, INV-1073, INV-1075)

US-format slash-delimited dates where both components are ≤ 12 (e.g., "12/03/2026", "03/10/2026", "09/08/2026"). The verifier's `_parse_date_token` cannot disambiguate MM/DD vs DD/MM and returns `DATE_AMBIGUOUS`.

### TAX_AMOUNT_MISMATCH (2 cases: INV-1071, INV-1072)

EU-format tax evidence with embedded percentages (e.g., "VAT (19%): EUR 699.20"). The `_TAX_ANCHOR_VALUE_RE` regex captures the first number after the tax anchor keyword ("19" — the percentage) instead of the actual tax amount ("699.20"). This produces a large delta (e.g., 680.2) that exceeds the 0.01 tolerance.

### ARITH_TOTAL_MISMATCH (1 case: INV-1074)

INV-1074 passes the verifier (all field-level checks succeed) but fails the arithmetic check. The raw invoice text contains a discount line that makes line items not sum to the stated total. This case may overlap with FF-001/L1 — consider reclassification.

### Why INV-1076 passes

INV-1076 (the only passing INV-107x record) succeeds because:
- Date "14/02/2026" is unambiguous (14 > 12, clearly DD/MM)
- Tax evidence "VAT: EUR 0.00" has no embedded percentage — regex captures "0.00" correctly
- No discount line — arithmetic passes

### Per-field accuracy

- **invoice_date**: 4/7 pass (57.1%)
- **tax_amount**: 5/7 pass (71.4%)

## Deferred Families

### FF-001 (12 cases, L1 input-text) — low priority

Synthetic invoices with arithmetically inconsistent line items. Extraction itself is correct (verify_extraction passes 12/12). Requires synthetic data generator fix, not extraction-level intervention. Not addressable by rescue policies.

### FF-004 (2 cases, L2 extraction-proposal) — low priority

GLC-4005 and APX-5004 carry only `match_fail` tags with no further diagnostic signal. Root cause unknown. Manual inspection required before any intervention can be designed.

## Priority Order

| Rank | Family | Count | Rationale |
|------|--------|-------|-----------|
| 1 | FF-003 | 6 | Largest production-relevant family. Confirmed, potentially addressable failure mechanisms. |
| 2 | FF-004 | 2 | Unknown root cause — manual inspection is a prerequisite. |
| 3 | FF-001 | 12 | Largest overall, but requires external fix (synthetic data generator). |

## Recommended Next Steps

1. **Expand gold dataset** with 15-20+ additional records containing `invoice_date` and `tax_amount` to enable statistically meaningful evaluation of FF-003 interventions.
2. **Evaluate DATE_AMBIGUOUS mitigation**: Require ISO date format (YYYY-MM-DD) in extraction prompts, or add document-level locale detection to resolve MM/DD vs DD/MM ambiguity.
3. **Evaluate TAX_AMOUNT_MISMATCH mitigation**: Improve `_TAX_ANCHOR_VALUE_RE` to skip embedded percentages, or restructure tax evidence to exclude percentage notation.
4. **Assess INV-1074 reclassification**: Determine whether it should remain in FF-003 (L3) or move to FF-001 (L1) given that the verifier passes and only arithmetic fails.
5. **Manually inspect FF-004 cases** (GLC-4005, APX-5004) to identify root cause.
6. **No rescue implementation yet** — dataset expansion and root cause confirmation come first.
