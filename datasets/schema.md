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

### `expected_fields` sub-keys

| Field | Type | Description |
|-------|------|-------------|
| `vendor` | string | Expected vendor name |
| `amount` | number | Expected invoice total |
| `has_po` | bool | Whether a PO reference exists |

### `mock_extraction` sub-keys

Each field is `{"value": <T>, "evidence": "<string>"}`:

| Field | value type | evidence |
|-------|-----------|----------|
| `vendor` | string | Verbatim vendor name substring from invoice text |
| `amount` | number | Verbatim total/amount line from invoice text |
| `has_po` | bool | Verbatim PO line from invoice text |

## Evidence Grounding Rules

Evidence strings **must be verbatim substrings** of the corresponding invoice text.
The runtime verifier (`src/verifier.py`) normalizes both evidence and raw text via
`_normalize_text()` (collapse whitespace, strip, casefold) before checking containment.

- **Amount evidence**: Use the total line exactly (e.g. `"TOTAL AMOUNT: 835.45"`,
  `"Total: $1,500.00"`, `"Total Due: 470.00"`)
- **Vendor evidence**: Use the vendor name as it appears in the text
- **has_po evidence (true)**: Use the explicit PO line (e.g. `"PO Number: PO-77321"`)
- **has_po evidence (false)**: Use `"PO: None"` (added to no-PO invoices)

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

## Adding New Gold Invoices

1. Add a `.txt` file to `datasets/gold_invoices/`
2. Append a JSON line to `datasets/expected.jsonl` following the schema above
3. Ensure all evidence strings are verbatim substrings of the invoice text
4. If the invoice has no PO, add an explicit `PO: None` line to the text file
5. Update `datasets/gold_invoices/README.md` with the new entry
