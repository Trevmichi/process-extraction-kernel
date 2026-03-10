# Evaluation Dataset Schema

## `expected.jsonl` — Gold Record Format

Each line is a JSON object with these required keys:

| Key | Type | Description |
|-----|------|-------------|
| `invoice_id` | string | Unique invoice identifier (e.g. `"INV-1001"`, `"NR-2001"`) |
| `file` | string | Filename in `gold_invoices/` (e.g. `"inv_001.txt"`) |
| `po_match` | bool | Test harness control flag — passed to `make_initial_state()` |
| `expected_status` | list[string] | Acceptable terminal statuses (OR semantics) |
| `expected_fields` | object | Expected extracted values: `vendor`, `amount`, `has_po` |
| `mock_extraction` | object | Per-invoice mock LLM return: `vendor`, `amount`, `has_po` |
| `tags` | list[string] | Scenario labels for filtering (e.g. `"happy_path"`, `"no_po"`) |

### Optional keys

| Key | Type | Description |
|-----|------|-------------|
| `expected_trace` | object | Lightweight path-correctness assertions (see below) |
| `expected_failures` | list[string] | Expected status values for negative-case cohorts |
| `notes` | string | Free text for dataset maintainers |

### `expected_trace` sub-keys

```json
{
  "must_include": ["route_decision", "n3"],
  "must_exclude": ["n_reject"]
}
```

| Key | Type | Description |
|-----|------|-------------|
| `must_include` | list[string] | Event types or node IDs that must appear in the audit log |
| `must_exclude` | list[string] | Event types or node IDs that must NOT appear in the audit log |

Labels are matched against parsed audit_log entries:
- Event types (e.g. `"route_decision"`, `"extraction"`, `"exception_station"`) match the `event` field
- Node IDs (e.g. `"n3"`, `"n_reject"`) match `from_node`, `selected`, or `node` fields

Node IDs come from `outputs/ap_master_manual_auto_patched.json` and may change only
when graph topology changes (guarded by the production graph regression test).

### `expected_failures`

Static annotation for cohort reporting. Values must match actual `state["status"]`
values (e.g. `"BAD_EXTRACTION"`, `"MISSING_DATA"`, `"EXCEPTION_NO_PO"`). This is
metadata for analysis, not an additional evaluation check.

### `expected_fields` sub-keys

| Field | Type | Description |
|-------|------|-------------|
| `vendor` | string | Expected vendor name |
| `amount` | number | Expected invoice total |
| `has_po` | bool | Whether a PO reference exists |
| `invoice_date` | string | Expected invoice date in ISO-8601 format (YYYY-MM-DD) |
| `tax_amount` | number | Expected tax/VAT amount |

### `mock_extraction` sub-keys

Each field is `{"value": <T>, "evidence": "<string>"}`:

| Field | value type | evidence |
|-------|-----------|----------|
| `vendor` | string | Verbatim vendor name substring from invoice text |
| `amount` | number | Verbatim total/amount line from invoice text |
| `has_po` | bool | Verbatim PO line from invoice text |
| `invoice_date` | string | Verbatim date line from invoice text |
| `tax_amount` | number | Verbatim tax/VAT line from invoice text |

## Evidence Grounding Rules

Evidence strings **must be verbatim substrings** of the corresponding invoice text.
The runtime verifier (`src/verifier.py`) normalizes both evidence and raw text via
`_normalize_text()` (collapse whitespace, strip, casefold) before checking containment.

- **Amount evidence**: Use the total line exactly (e.g. `"TOTAL AMOUNT: 835.45"`,
  `"Total: $1,500.00"`, `"Total Due: 470.00"`)
- **Vendor evidence**: Use the vendor name as it appears in the text
- **has_po evidence (true)**: Use the explicit PO line (e.g. `"PO Number: PO-77321"`)
- **has_po evidence (false)**: Use `"PO: None"` (added to no-PO invoices).
  `has_po.evidence` must always be a non-null grounded string, even when
  `value=false`. Null is not allowed.
- **Invoice date evidence**: Use the date line exactly (e.g. `"Date: 01/15/2026"`,
  `"Invoice Date: 25/06/2026"`)
- **Tax amount evidence**: Use the tax/VAT line exactly (e.g. `"Tax: $125.00"`,
  `"VAT: 0.00"`)

### PO Evidence Rule

PO reference must be an **explicit `PO: ...` line** for has_po evidence grounding,
not prose mentions. For example, TG-3006 contains "referencing your purchase order
IT-9006" in prose — this is a PO reference (has_po=true), but the evidence string
should reference the prose text directly: `"purchase order IT-9006"`.

## `po_match` — Test Harness Control Flag

`po_match` is **not an extracted field**. It is a control flag passed to
`make_initial_state(..., po_match=<bool>)` which determines match behavior in the
graph's MATCH_3_WAY node. In mock mode, this is the source of truth for whether a
PO match succeeds or fails.

When evaluating real LLM output (--live mode), `po_match` should be set based on
external PO matching logic, not extracted from invoice text.

## Mock Dispatch

The mock LLM (`build_mock_dispatch()`) extracts the invoice ID from the prompt using:

```
(INV-\d{4}|NR-\d{4}|TG-\d{4}|GLC-\d{4}|APX-\d{4})
```

If no invoice ID is found in mock mode, `ValueError` is raised (fail-fast, no silent
fallback). Validator prompts (containing "validator") always return `{"is_valid": True}`.

## Field Comparison Normalization

When comparing extracted fields against expected values:

| Field | Normalization | Match rule |
|-------|--------------|------------|
| `vendor` | `casefold()` + whitespace collapse | Normalized strings equal |
| `amount` | None | `abs(expected - actual) <= 0.01` |
| `has_po` | None | Strict equality |
| `invoice_date` | None | Strict string equality |
| `tax_amount` | None | `abs(expected - actual) <= 0.01` |

## Tag Taxonomy

Tags should be lowercase `snake_case`. Recommended categories:

**Core scenario tags** (at least one required):

| Tag | Meaning |
|-----|---------|
| `happy_path` | Normal invoice with PO, amount under threshold |
| `no_po` | No purchase order reference |
| `match_fail` | PO exists but 3-way match fails |
| `bad_extraction` | Expected extraction failure |
| `missing_data` | Expected missing-data rejection |

**Format tags** (optional, describe invoice structure):

`single_line`, `multi_line`, `table_like`, `email_style`, `footer_total`,
`multi_section`, `simple`, `weird_spacing`, `multiple_totals`, `noisy_header`,
`prose_po_reference`, `ocr_spacing`

**Adversarial tags** (optional, target specific anti-patterns):

`threshold_edge_exact`, `po_false_positive_prose`, `duplicate_total_lines`,
`vendor_alias_variation`, `footer_total_vs_amount_due_conflict`,
`multi_currency_symbol_noise`, `date_us_format`, `date_eu_format`,
`tax_standard`, `tax_complex_lines`, `tax_zero_explicit`

**Vendor tags** (optional, prefix with `vendor_`):

`vendor_acme`, `vendor_north_river`, `vendor_global_logistics`, `vendor_trigate`,
`vendor_apex`, `vendor_horizon`, `vendor_delta`, `vendor_silverline`,
`vendor_atlas`, `vendor_metrotech`

---

## Adding New Gold Invoices

1. Add a `.txt` file to `datasets/gold_invoices/`
2. Append a JSON line to `datasets/expected.jsonl` following the schema above
3. Ensure all evidence strings are verbatim substrings of the invoice text
4. If the invoice has no PO, add an explicit `PO: None` line to the text file
   (`has_po.evidence` must be a non-null grounded string)
5. Update `datasets/gold_invoices/README.md` with the new entry
6. Validate:
   ```bash
   python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v
   python eval_runner.py --filter <invoice_ids> --show-failures
   ```
