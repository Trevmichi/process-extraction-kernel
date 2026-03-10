# Gold Invoice Text Files

70 invoice text files across 13 vendors for evaluation of the AP extraction pipeline.

| File | Invoice ID | Vendor | Scenario |
|------|-----------|--------|----------|
| inv_001.txt | INV-1001 | Acme Industrial Supply | happy_path |
| inv_002.txt | INV-1002 | Acme Industrial Supply | happy_path |
| inv_003.txt | INV-1003 | Acme Industrial Supply | no_po |
| inv_004.txt | INV-1004 | Acme Industrial Supply | happy_path |
| inv_005.txt | INV-1005 | Acme Industrial Supply | match_fail |
| inv_006.txt | INV-1006 | Acme Industrial Supply | happy_path |
| inv_007.txt | NR-2001 | NorthRiver Office & Facility Solutions | happy_path |
| inv_008.txt | NR-2002 | NorthRiver Office & Facility Solutions | no_po |
| inv_009.txt | NR-2003 | NorthRiver Office & Facility Solutions | match_fail |
| inv_010.txt | NR-2004 | NorthRiver Office & Facility Solutions | happy_path |
| inv_011.txt | NR-2005 | NorthRiver Office & Facility Solutions | happy_path |
| inv_012.txt | NR-2006 | NorthRiver Office & Facility Solutions | happy_path |
| inv_013.txt | TG-3001 | TechGear IT Services | happy_path |
| inv_014.txt | TG-3002 | TechGear IT Services | happy_path |
| inv_015.txt | TG-3003 | TechGear IT Services | no_po |
| inv_016.txt | TG-3004 | TechGear IT Services | happy_path |
| inv_017.txt | TG-3005 | TechGear IT Services | happy_path |
| inv_018.txt | TG-3006 | TechGear IT Services | match_fail |
| inv_019.txt | GLC-4001 | Global Logistics Corp | happy_path |
| inv_020.txt | GLC-4002 | Global Logistics Corp | happy_path |
| inv_021.txt | GLC-4003 | Global Logistics Corp | happy_path |
| inv_022.txt | GLC-4004 | Global Logistics Corp | no_po |
| inv_023.txt | GLC-4005 | Global Logistics Corp | match_fail |
| inv_024.txt | GLC-4006 | Global Logistics Corp | happy_path |
| inv_025.txt | APX-5001 | Apex Maintenance Co. | happy_path |
| inv_026.txt | APX-5002 | Apex Maintenance Co. | happy_path |
| inv_027.txt | APX-5003 | Apex Maintenance Co. | happy_path |
| inv_028.txt | APX-5004 | Apex Maintenance Co. | match_fail |
| inv_029.txt | APX-5005 | Apex Maintenance Co. | no_po |
| inv_030.txt | APX-5006 | Apex Maintenance Co. | happy_path |
| inv_031.txt | INV-1031 | ACME Industrial Supply | happy_path |
| inv_032.txt | INV-1032 | North River Components | happy_path, table_like |
| inv_033.txt | INV-1033 | Global Logistics Corp | happy_path, email_style |
| inv_034.txt | INV-1034 | TriGate Manufacturing | happy_path, multi_section |
| inv_035.txt | INV-1035 | Apex Office Solutions | happy_path, footer_total |
| inv_036.txt | INV-1036 | Horizon Freight Systems | happy_path |
| inv_037.txt | INV-1037 | Delta Mechanical Services | happy_path, table_like |
| inv_038.txt | INV-1038 | Silverline Packaging | happy_path |
| inv_039.txt | INV-1039 | Atlas Electrical Supply | no_po |
| inv_040.txt | INV-1040 | MetroTech Services | no_po, footer_total |
| inv_041.txt | INV-1041 | ACME Industrial Supply | no_po, email_style |
| inv_042.txt | INV-1042 | North River Components | no_po, simple |
| inv_043.txt | INV-1043 | Global Logistics Corp | no_po |
| inv_044.txt | INV-1044 | TriGate Manufacturing | match_fail |
| inv_045.txt | INV-1045 | Apex Office Solutions | match_fail |
| inv_046.txt | INV-1046 | Horizon Freight Systems | match_fail |
| inv_047.txt | INV-1047 | Delta Mechanical Services | match_fail |
| inv_048.txt | INV-1048 | Silverline Packaging | multiple_totals |
| inv_049.txt | INV-1049 | Atlas Electrical Supply | weird_spacing |
| inv_050.txt | INV-1050 | MetroTech Services | no_po, table_like |
| inv_057.txt | INV-1057 | Horizon Freight Systems | threshold_edge_exact, happy_path |
| inv_058.txt | INV-1058 | Horizon Freight Systems | threshold_edge_exact, no_po |
| inv_059.txt | INV-1059 | Delta Mechanical Services | po_false_positive_prose, no_po |
| inv_060.txt | INV-1060 | Delta Mechanical Services | po_false_positive_prose, no_po |
| inv_061.txt | INV-1061 | Silverline Packaging | duplicate_total_lines, multiple_totals, happy_path |
| inv_062.txt | INV-1062 | Silverline Packaging | duplicate_total_lines, multiple_totals, happy_path |
| inv_063.txt | INV-1063 | Atlas Electrical Supply | ocr_spacing, weird_spacing, happy_path |
| inv_064.txt | INV-1064 | MetroTech Services | ocr_spacing, weird_spacing, no_po |
| inv_065.txt | INV-1065 | Acme Industrial Supply, LLC | vendor_alias_variation, happy_path |
| inv_066.txt | INV-1066 | Acme Industrial Supply Inc. | vendor_alias_variation, happy_path |
| inv_067.txt | INV-1067 | Atlas Electrical Supply | footer_total_vs_amount_due_conflict, happy_path |
| inv_068.txt | INV-1068 | MetroTech Services | multi_currency_symbol_noise, happy_path |
| inv_069.txt | INV-1069 | Acme Industrial Supply | date_us_format, tax_standard, happy_path |
| inv_070.txt | INV-1070 | NorthRiver Office Solutions | date_us_format, tax_standard, happy_path |
| inv_071.txt | INV-1071 | Global Logistics Corp | date_eu_format, tax_standard, happy_path |
| inv_072.txt | INV-1072 | Horizon Freight Systems | date_eu_format, tax_standard, happy_path |
| inv_073.txt | INV-1073 | Delta Mechanical Services | tax_complex_lines, happy_path |
| inv_074.txt | INV-1074 | Silverline Packaging | tax_complex_lines, happy_path |
| inv_075.txt | INV-1075 | Atlas Electrical Supply | tax_zero_explicit, happy_path |
| inv_076.txt | INV-1076 | MetroTech Services | tax_zero_explicit, happy_path |

---

## Adding New Gold Invoices (Checklist)

1. Create `datasets/gold_invoices/inv_NNN.txt` with the invoice text
   - Include vendor name verbatim on a line
   - Include an amount line (e.g. `Total: 1234.56`)
   - Include a PO line (e.g. `PO Number: PO-12345`) or `PO: None` for no-PO invoices
   - **Important**: no-PO invoices must have an explicit `PO: None` line

2. Append one JSON line to `datasets/expected.jsonl` with all required keys:
   `invoice_id`, `file`, `po_match`, `expected_status`, `expected_fields`,
   `mock_extraction`, `tags`

3. Ensure all `mock_extraction.*.evidence` strings are **verbatim substrings**
   of the invoice text (after `_normalize_text` normalization)

4. Set `has_po.evidence` to a non-null grounded string (use `"PO: None"` for
   no-PO invoices). Null evidence is not allowed.

5. Add a row to this README catalog table

6. Validate:
   ```bash
   python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v
   python eval_runner.py --filter <invoice_ids> --show-failures
   ```
