# Evaluation Harness

## Overview

The evaluation harness validates the AP extraction pipeline against 50 gold
invoices with known expected outputs. It supports two modes:

- **Mock mode** (default): deterministic, no LLM needed. Uses per-invoice
  mock extraction payloads from `datasets/expected.jsonl`.
- **Live mode** (`--live`): real Ollama LLM. Requires `gemma3:12b` running
  locally.

**Files**:

| File | Role |
|------|------|
| `eval_runner.py` | Evaluation runner (mock + live modes) |
| `tests/test_eval_harness.py` | CI validation of dataset integrity |
| `datasets/expected.jsonl` | 50 gold records (1 JSON line per invoice) |
| `datasets/gold_invoices/` | 50 invoice text files |
| `datasets/gold_invoices/README.md` | Invoice catalog with scenario labels |
| `datasets/schema.md` | JSON schema reference for expected.jsonl |

---

## Dataset Layout

```
datasets/
  expected.jsonl                    # 50 gold records
  schema.md                        # JSON schema
  gold_invoices/
    README.md                      # catalog
    inv_001.txt ... inv_050.txt    # 50 invoice text files
```

**Coverage**: 13 vendors, 3 core scenario types, multiple format tags:

| Scenario | Count | Description |
|----------|-------|-------------|
| `happy_path` | 28 | Normal invoices with PO, amount under/over threshold |
| `no_po` | 11 | No purchase order -> routes to MANUAL_REVIEW_NO_PO |
| `match_fail` | 9 | PO match fails -> routes to MATCH_FAILED exception |
| `multiple_totals` | 1 | Invoice with multiple dollar amounts |
| `weird_spacing` | 1 | Invoice with irregular whitespace |

---

## Expected JSONL Schema

Each line in `datasets/expected.jsonl` is a JSON object:

```json
{
  "invoice_id": "INV-1001",
  "file": "inv_001.txt",
  "po_match": true,
  "expected_status": ["APPROVED", "PAID"],
  "expected_fields": {
    "vendor": "Acme Industrial Supply",
    "amount": 835.45,
    "has_po": true
  },
  "mock_extraction": {
    "vendor": {"value": "Acme Industrial Supply", "evidence": "Acme Industrial Supply"},
    "amount": {"value": 835.45, "evidence": "TOTAL AMOUNT: 835.45"},
    "has_po": {"value": true, "evidence": "PO Number: PO-77321"}
  },
  "tags": ["happy_path", "under_threshold"]
}
```

**Required fields**:

| Field | Type | Notes |
|-------|------|-------|
| `invoice_id` | string | Unique ID (INV-, NR-, TG-, GLC-, APX- prefixed) |
| `file` | string | Filename in `gold_invoices/` |
| `po_match` | bool | **Test harness control flag** -- passed to `make_initial_state()`, NOT an extracted field. Controls whether MATCH_3_WAY succeeds or fails. |
| `expected_status` | list[string] | Acceptable terminal statuses (OR logic: any match is a pass) |
| `expected_fields` | object | Ground truth for `vendor`, `amount`, `has_po` |
| `mock_extraction` | object | Per-invoice mock LLM response. Each field has `value` and `evidence`. |
| `tags` | list[string] | Scenario labels for filtering and reporting |

**Optional fields**:

| Field | Type | Notes |
|-------|------|-------|
| `expected_trace` | object | `{must_include: [str], must_exclude: [str]}` — lightweight path assertions against audit_log |
| `expected_failures` | list[string] | Expected status values for negative-case cohort reporting |
| `notes` | string | Free text for dataset maintainers |

---

## Evidence Grounding Rules

Every `mock_extraction.*.evidence` value must be a **verbatim substring** of
the corresponding invoice text file, after text normalization.

**Text normalization** (see `src/verifier.py: _normalize_text`):
- Collapse multiple whitespace characters to a single space
- Strip leading/trailing whitespace
- Casefold (lowercase)

### Per-field rules

**Vendor** (see `src/verifier.py: _verify_vendor`):
1. `value` must be non-empty
2. `evidence` must be a substring of the normalized raw text
3. `value` must appear within `evidence`

**Amount** (see `src/verifier.py: _verify_amount`):
1. `value` must be numeric (int or float)
2. `evidence` must be a substring of the normalized raw text
3. All numbers are extracted from `evidence` via regex
   (`[\d,]+\.?\d*|\.\d+`, after stripping currency symbols `$`, etc.)
4. If multiple numbers: disambiguate using a 30-character keyword window.
   Keywords: `"total"`, `"amount due"`, `"balance due"`, `"sum"`.
   The number preceded by a keyword wins.
5. The parsed number must match `value` within `abs(delta) <= 0.01`

**has_po** (see `src/verifier.py: _verify_has_po`):
1. `value` must be a boolean
2. `evidence` must be a non-null grounded string (null is not allowed)
3. If `value` is `true`: evidence must match the PO regex:
   `\b(PO|Purchase\s+Order)\b|\bP\.O\.(?:\s|$|#)|PO-?\d+`
4. If `value` is `false`: no PO pattern check. Use `"PO: None"` as evidence
   (must appear in the invoice text).

---

## Mock Dispatch

In mock mode, `eval_runner.py` patches `src.agent.nodes._call_llm_json` with
a deterministic dispatcher that returns mock payloads from `expected.jsonl`.

**Invoice ID regex**: `(INV-\d{4}|NR-\d{4}|TG-\d{4}|GLC-\d{4}|APX-\d{4})`

**Behavior**:
1. Search the LLM prompt for a matching invoice ID
2. If found: return `mock_extraction` from the corresponding gold record
3. If NOT found: **raise `ValueError`** immediately (fail-fast, no silent
   fallback)
4. Special case: prompts containing `"validator"` (from VALIDATE_FIELDS node)
   always return `{"is_valid": true}` without ID extraction

---

## Field Comparison

The eval runner compares actual extracted fields against expected fields using
normalized comparison rules (see `eval_runner.py`):

| Field | Normalization | Match Rule |
|-------|---------------|------------|
| `vendor` | Casefold + whitespace collapse | Normalized strings equal |
| `amount` | None | `abs(expected - actual) <= 0.01` |
| `has_po` | None | Strict boolean equality |

---

## Failure Bucketing

Each invoice is assigned a deterministic `failure_bucket` based on comparison
results (see `eval_runner.py: classify_failure`):

| Bucket | Meaning |
|--------|---------|
| `pass` | Terminal status matches AND all fields match |
| `terminal_mismatch` | Terminal status wrong, but all fields correct |
| `field_mismatch` | Terminal status correct, but one or more fields wrong |
| `both_terminal_and_field_mismatch` | Both terminal and field failures |

Per-invoice results also include `field_mismatches` (list of failing field
names) for targeted debugging.

---

## Trace Assertions

Gold records may optionally include `expected_trace` to validate routing paths
(see `eval_runner.py: check_trace`):

```json
{
  "expected_trace": {
    "must_include": ["route_decision", "n3"],
    "must_exclude": ["n_reject"]
  }
}
```

Labels are matched against parsed audit_log entries:
- **Event types** (e.g. `"route_decision"`) match the `event` field
- **Node IDs** (e.g. `"n3"`) match `from_node`, `selected`, or `node` fields

If the audit log is empty or unparseable, all `must_include` items are reported
as missing (no exceptions raised).

---

## Tag-Based Metrics

The eval runner computes per-tag cohort metrics automatically from the `tags`
field on each gold record (see `eval_runner.py: compute_metrics`):

```json
{
  "by_tag": {
    "no_po": {
      "count": 11,
      "terminal_accuracy": {"correct": 11, "total": 11, "accuracy": 1.0},
      "field_accuracy": {
        "vendor": {"correct": 11, "total": 11, "accuracy": 1.0},
        "overall": {"correct": 33, "total": 33, "accuracy": 1.0}
      }
    }
  }
}
```

Tag breakdown is always included in `eval_report.json`. For the markdown
report, use `--group-by-tag` to include the tag breakdown table.

---

## Metrics

| Metric | Calculation |
|--------|-------------|
| **Terminal accuracy** | `actual_status in expected_status` for each invoice. Count correct / 50. |
| **Field accuracy** | 3 fields x 50 invoices = 150 comparisons. Count correct / 150. |
| **Unknown rate** | Count of invoices where `match_result == "UNKNOWN"` / 50. |
| **Confusion matrix** | Rows: `expected_status[0]` (primary). Columns: `actual_status`. |
| **By-tag metrics** | Terminal + field accuracy computed per tag cohort. |

---

## Running the Eval

```bash
# Mock mode (default, no LLM needed)
python eval_runner.py

# Live mode (requires Ollama with gemma3:12b)
python eval_runner.py --live

# Filter to specific invoices
python eval_runner.py --filter INV-1001,NR-2003

# Show failures grouped by bucket
python eval_runner.py --show-failures

# Include tag breakdown in markdown report
python eval_runner.py --group-by-tag

# Custom paths
python eval_runner.py --expected datasets/expected.jsonl --graph outputs/ap_master_manual_auto_patched.json
```

**Output files** (generated, not committed):
- `eval_report.json` -- full metrics, tag breakdown, and per-invoice details
- `eval_report.md` -- human-readable summary table

---

## Tag Taxonomy

Tags should be lowercase `snake_case`. Recommended categories:

**Core scenario**: `happy_path`, `no_po`, `match_fail`, `bad_extraction`,
`missing_data`

**Format**: `single_line`, `multi_line`, `table_like`, `email_style`,
`footer_total`, `multi_section`, `simple`, `weird_spacing`, `multiple_totals`,
`noisy_header`, `prose_po_reference`

**Vendor**: `vendor_acme`, `vendor_north_river`, `vendor_global_logistics`,
`vendor_trigate`, `vendor_apex`, `vendor_horizon`, `vendor_delta`,
`vendor_silverline`, `vendor_atlas`, `vendor_metrotech`

---

## Adding a New Gold Invoice

1. **Create invoice text file**: `datasets/gold_invoices/inv_NNN.txt`
   - Include vendor name verbatim on a line
   - Include an amount line (e.g. `Total: 1234.56`)
   - Include a PO line (e.g. `PO Number: PO-12345`) or `PO: None` for no-PO
   - **Important**: `has_po.evidence` must be a non-null grounded string.
     Use `"PO: None"` for no-PO invoices (null is not allowed).

2. **Append gold record** to `datasets/expected.jsonl`:
   ```json
   {
     "invoice_id": "NEW-9999",
     "file": "inv_NNN.txt",
     "po_match": true,
     "expected_status": ["APPROVED", "PAID"],
     "expected_fields": {
       "vendor": "Vendor Name",
       "amount": 1234.56,
       "has_po": true
     },
     "mock_extraction": {
       "vendor": {"value": "Vendor Name", "evidence": "Vendor Name"},
       "amount": {"value": 1234.56, "evidence": "Total: 1234.56"},
       "has_po": {"value": true, "evidence": "PO Number: PO-12345"}
     },
     "tags": ["happy_path", "vendor_new"]
   }
   ```

3. **Critical**: all `evidence` strings must be exact substrings of the
   invoice text (after `_normalize_text` is applied to both).

4. **Update catalog**: add an entry to `datasets/gold_invoices/README.md`.

5. **Validate**:
   ```bash
   python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v
   python eval_runner.py --filter NEW-9999 --show-failures
   ```
