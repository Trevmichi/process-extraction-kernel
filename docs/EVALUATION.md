# Evaluation Harness

## Overview

The evaluation harness validates the AP extraction pipeline against 30 gold
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
| `datasets/expected.jsonl` | 30 gold records (1 JSON line per invoice) |
| `datasets/gold_invoices/` | 30 invoice text files |
| `datasets/gold_invoices/README.md` | Invoice catalog with scenario labels |
| `datasets/schema.md` | JSON schema reference for expected.jsonl |

---

## Dataset Layout

```
datasets/
  expected.jsonl                    # 30 gold records
  schema.md                        # JSON schema
  gold_invoices/
    README.md                      # catalog
    inv_001.txt ... inv_030.txt    # 30 invoice text files
```

**Coverage**: 5 vendors, 6 invoices each, 3 scenario types:

| Scenario | Count | Description |
|----------|-------|-------------|
| `happy_path` | 20 | Normal invoices with PO, amount under/over threshold |
| `no_po` | 5 | No purchase order -> routes to MANUAL_REVIEW_NO_PO |
| `match_fail` | 5 | PO match fails -> routes to MATCH_FAILED exception |

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

**Key fields**:

| Field | Type | Notes |
|-------|------|-------|
| `invoice_id` | string | Unique ID (INV-, NR-, TG-, GLC-, APX- prefixed) |
| `file` | string | Filename in `gold_invoices/` |
| `po_match` | bool | **Test harness control flag** -- passed to `make_initial_state()`, NOT an extracted field. Controls whether MATCH_3_WAY succeeds or fails. |
| `expected_status` | list[string] | Acceptable terminal statuses (OR logic: any match is a pass) |
| `expected_fields` | object | Ground truth for `vendor`, `amount`, `has_po` |
| `mock_extraction` | object | Per-invoice mock LLM response. Each field has `value` and `evidence`. |
| `tags` | list[string] | Scenario labels for filtering and reporting |

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
2. `evidence` must be a substring of the normalized raw text
3. If `value` is `true`: evidence must match the PO regex:
   `\b(PO|Purchase\s+Order)\b|\bP\.O\.(?:\s|$|#)|PO-?\d+`
4. If `value` is `false`: no PO pattern check (evidence is typically
   `"PO: None"`)

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

## Metrics

| Metric | Calculation |
|--------|-------------|
| **Terminal accuracy** | `actual_status in expected_status` for each invoice. Count correct / 30. |
| **Field accuracy** | 3 fields x 30 invoices = 90 comparisons. Count correct / 90. |
| **Unknown rate** | Count of invoices where `match_result == "UNKNOWN"` / 30. |
| **Confusion matrix** | Rows: `expected_status[0]` (primary). Columns: `actual_status`. |

---

## Running the Eval

```bash
# Mock mode (default, no LLM needed)
python eval_runner.py

# Live mode (requires Ollama with gemma3:12b)
python eval_runner.py --live

# Filter to specific invoices
python eval_runner.py --filter INV-1001,NR-2003

# Custom paths
python eval_runner.py --expected datasets/expected.jsonl --graph outputs/ap_master_manual_auto_patched.json
```

**Output files** (generated, not committed):
- `eval_report.json` -- full metrics and per-invoice details
- `eval_report.md` -- human-readable summary table

---

## Adding a New Gold Invoice

1. **Create invoice text file**: `datasets/gold_invoices/inv_NNN.txt`
   - Include vendor name verbatim on a line
   - Include an amount line (e.g. `Total: 1234.56`)
   - Include a PO line (e.g. `PO Number: PO-12345` or `PO: None`)

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
     "tags": ["happy_path"]
   }
   ```

3. **Critical**: all `evidence` strings must be exact substrings of the
   invoice text (after `_normalize_text` is applied to both).

4. **Update catalog**: add an entry to `datasets/gold_invoices/README.md`.

5. **Validate**:
   ```bash
   python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v
   ```
   This test reads every gold record and confirms that each
   `mock_extraction.*.evidence` is a substring of the corresponding invoice
   file (using the same normalization as the verifier).
