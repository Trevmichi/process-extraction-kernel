"""
test_schemas.py
Validate JSON Schema artifacts against runtime shapes and concrete outputs.

Each schema is grounded in the Python contracts (TypedDicts, dataclasses,
Literal types) and tested by round-tripping real runtime outputs through
jsonschema validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"


def _load_schema(name: str) -> dict:
    """Load and return a JSON Schema from the schema/ directory."""
    path = SCHEMA_DIR / name
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    # Validate the schema itself is valid JSON Schema
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


# -----------------------------------------------------------------------
# Extraction Payload
# -----------------------------------------------------------------------

class TestExtractionPayloadSchema:
    """Validate extraction_payload_v1.json against runtime shapes."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("extraction_payload_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        # Covered by _load_schema, but explicit for clarity
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_minimal_valid_payload(self):
        """Three required fields with value + evidence."""
        payload = {
            "vendor": {"value": "Acme Corp", "evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
        }
        self._validate(payload)

    def test_full_payload_with_optional_fields(self):
        payload = {
            "vendor": {"value": "Acme Corp", "evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
            "invoice_date": {"value": "2024-01-15", "evidence": "Date: Jan 15, 2024"},
            "tax_amount": {"value": 8.50, "evidence": "Tax: $8.50"},
        }
        self._validate(payload)

    def test_error_payload(self):
        """_error shape is mutually exclusive with field entries."""
        payload = {"_error": "LLM timeout after 30s"}
        self._validate(payload)

    def test_null_value_allowed(self):
        """value can be null (e.g., has_po when uncertain)."""
        payload = {
            "vendor": {"value": "Acme Corp", "evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": None, "evidence": ""},
        }
        self._validate(payload)

    def test_missing_required_field_rejected(self):
        """Missing 'vendor' should fail validation."""
        payload = {
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_missing_evidence_key_rejected(self):
        """Field without 'evidence' key should fail."""
        payload = {
            "vendor": {"value": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_missing_value_key_rejected(self):
        """Field without 'value' key should fail."""
        payload = {
            "vendor": {"evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_extra_top_level_key_rejected(self):
        """Unknown top-level keys should fail (additionalProperties: false)."""
        payload = {
            "vendor": {"value": "Acme Corp", "evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: 100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
            "unknown_field": {"value": "x", "evidence": "y"},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_error_with_extra_keys_allowed(self):
        """Error payloads may carry additional debug info."""
        payload = {"_error": "timeout", "raw_response": "..."}
        self._validate(payload)


# -----------------------------------------------------------------------
# Failure Codes
# -----------------------------------------------------------------------

class TestFailureCodesSchema:
    """Validate failure_codes_v1.json against verifier FailureCode Literal."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("failure_codes_v1.json")

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_all_failure_codes_present(self):
        """Every FailureCode literal must appear in the schema enum."""
        from src.verifier import FailureCode
        literal_codes = set(FailureCode.__args__)
        schema_codes = set(self.schema["enum"])
        assert literal_codes == schema_codes, (
            f"Mismatch: in Literal only: {literal_codes - schema_codes}, "
            f"in schema only: {schema_codes - literal_codes}"
        )

    def test_valid_code_validates(self):
        jsonschema.validate("AMOUNT_MISMATCH", self.schema)

    def test_invalid_code_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate("NOT_A_REAL_CODE", self.schema)

    def test_struct_code_rejected(self):
        """STRUCT_* codes are a separate family and must not validate."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate("STRUCT_MISSING_VENDOR", self.schema)

    def test_enum_count(self):
        """Sanity: enum has exactly 25 codes (matching FailureCode Literal)."""
        assert len(self.schema["enum"]) == 25


# -----------------------------------------------------------------------
# Provenance Report
# -----------------------------------------------------------------------

class TestProvenanceReportSchema:
    """Validate provenance_report_v1.json against runtime shapes."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("provenance_report_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_default_provenance_validates(self):
        """_default_provenance() output must validate against schema."""
        from src.verifier import _default_provenance
        prov = _default_provenance()
        self._validate(prov)

    def test_full_provenance_with_optional_fields(self):
        """Provenance with all 5 fields (including invoice_date, tax_amount)."""
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 10, "match_tier": "exact_match"},
            "amount": {
                "grounded": True,
                "parsed_evidence": 100.0,
                "delta": 0.0,
                "evidence_found_at": 25,
                "match_tier": "exact_match",
            },
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "exact_match"},
            "invoice_date": {
                "grounded": True,
                "evidence_found_at": 50,
                "normalized_value": "2024-01-15",
                "normalized_evidence": "2024-01-15",
                "match_tier": "normalized_match",
            },
            "tax_amount": {
                "grounded": True,
                "evidence_found_at": 75,
                "anchor_found": True,
                "parsed_evidence": 8.50,
                "delta": 0.0,
                "match_tier": "exact_match",
            },
        }
        self._validate(prov)

    def test_amount_without_evidence_found_at(self):
        """Amount from _default_provenance() lacks evidence_found_at — valid."""
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
        }
        self._validate(prov)

    def test_amount_with_evidence_found_at(self):
        """Amount after _verify_amount() has evidence_found_at — valid."""
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {
                "grounded": True,
                "parsed_evidence": 100.0,
                "delta": 0.0,
                "evidence_found_at": 42,
                "match_tier": "exact_match",
            },
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
        }
        self._validate(prov)

    def test_null_values_allowed(self):
        """Nullable fields (parsed_evidence, delta, po_pattern_found, etc.)."""
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
        }
        self._validate(prov)

    def test_missing_required_vendor_rejected(self):
        """vendor is required (always present from _default_provenance)."""
        prov = {
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None},
            "has_po": {"grounded": False, "po_pattern_found": None},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(prov)

    def test_arithmetic_provenance_accepted(self):
        """Provenance with arithmetic property (total_sum + tax_rate) validates."""
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 10, "match_tier": "exact_match"},
            "amount": {"grounded": True, "parsed_evidence": 100.0, "delta": 0.0,
                       "evidence_found_at": 25, "match_tier": "exact_match"},
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "exact_match"},
            "arithmetic": {
                "checks_run": ["total_sum", "tax_rate"],
                "passed": True,
                "codes": [],
                "total_sum": {
                    "subtotal": 90.0, "taxes": 10.0, "fees": 0.0,
                    "expected": 100.0, "actual": 100.0, "delta": 0.0,
                },
                "tax_rate": {
                    "rate_pct": 10.0, "computed": 9.0, "stated": 10.0, "delta": 1.0,
                },
            },
        }
        self._validate(prov)

    def test_arithmetic_provenance_partial_accepted(self):
        """Arithmetic with only checks_run/passed/codes (no detail sub-objects)."""
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 10, "match_tier": "normalized_match"},
            "amount": {"grounded": True, "parsed_evidence": 100.0, "delta": 0.0, "match_tier": "exact_match"},
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "not_found"},
            "arithmetic": {
                "checks_run": [],
                "passed": True,
                "codes": [],
            },
        }
        self._validate(prov)

    def test_arithmetic_total_sum_missing_field_rejected(self):
        """total_sum missing required field → rejected."""
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 10, "match_tier": "exact_match"},
            "amount": {"grounded": True, "parsed_evidence": 100.0, "delta": 0.0, "match_tier": "exact_match"},
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "exact_match"},
            "arithmetic": {
                "checks_run": ["total_sum"],
                "passed": True,
                "codes": [],
                "total_sum": {
                    "subtotal": 90.0, "taxes": 10.0,
                    # missing fees, expected, actual, delta
                },
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(prov)

    def test_extra_field_rejected(self):
        """Unknown top-level field rejected."""
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
            "unknown": {"grounded": False},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(prov)

    def test_vendor_missing_grounded_rejected(self):
        """VendorProvenance requires grounded."""
        prov = {
            "vendor": {"evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(prov)

    def test_real_verifier_output_validates(self):
        """Round-trip: verify_extraction() output validates against schema."""
        from src.verifier import verify_extraction

        raw = "Invoice from Acme Corp\nTotal: $100.00\nPO: PO-123"
        extraction = {
            "vendor": {"value": "Acme Corp", "evidence": "Acme Corp"},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-123"},
        }
        _valid, _codes, prov = verify_extraction(raw, extraction)
        self._validate(prov)


# -----------------------------------------------------------------------
# Route Record
# -----------------------------------------------------------------------

class TestRouteRecordSchema:
    """Validate route_record_v1.json against RouteRecord.to_dict() output."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("route_record_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_minimal_route_record(self):
        """Single unconditional edge — simplest valid record."""
        record = {
            "gateway_id": "n8",
            "outgoing_edge_set": [{"to": "n9", "raw_condition": None}],
            "normalized_conditions": [
                {"to": "n9", "raw_condition": None, "normalized_condition": None}
            ],
            "predicate_results": [
                {"to": "n9", "normalized_condition": None, "matched": None, "phase": "fallback"}
            ],
            "selected_edge": {"to": "n9", "condition": None},
            "reason": "single_edge",
            "exception_mapping": None,
            "schema_version": "route_record_v1",
        }
        self._validate(record)

    def test_conditional_route_record(self):
        """Route with conditional matching."""
        record = {
            "gateway_id": "n4",
            "outgoing_edge_set": [
                {"to": "n5", "raw_condition": "match_result == \"MATCH\""},
                {"to": "n6", "raw_condition": "match_result == \"NO_MATCH\""},
            ],
            "normalized_conditions": [
                {"to": "n5", "raw_condition": "match_result == \"MATCH\"",
                 "normalized_condition": "match_result == \"MATCH\""},
                {"to": "n6", "raw_condition": "match_result == \"NO_MATCH\"",
                 "normalized_condition": "match_result == \"NO_MATCH\""},
            ],
            "predicate_results": [
                {"to": "n5", "normalized_condition": "match_result == \"MATCH\"",
                 "matched": True, "phase": "conditional"},
                {"to": "n6", "normalized_condition": "match_result == \"NO_MATCH\"",
                 "matched": False, "phase": "conditional"},
            ],
            "selected_edge": {"to": "n5", "condition": "match_result == \"MATCH\""},
            "reason": "condition_match",
            "exception_mapping": None,
            "schema_version": "route_record_v1",
        }
        self._validate(record)

    def test_ambiguous_route_with_exception(self):
        """Ambiguous route → exception station mapping."""
        record = {
            "gateway_id": "n10",
            "outgoing_edge_set": [
                {"to": "n11", "raw_condition": "x == true"},
                {"to": "n12", "raw_condition": "x == false"},
            ],
            "normalized_conditions": [
                {"to": "n11", "raw_condition": "x == true",
                 "normalized_condition": "x == true"},
                {"to": "n12", "raw_condition": "x == false",
                 "normalized_condition": "x == false"},
            ],
            "predicate_results": [
                {"to": "n11", "normalized_condition": "x == true",
                 "matched": True, "phase": "conditional"},
                {"to": "n12", "normalized_condition": "x == false",
                 "matched": True, "phase": "conditional"},
            ],
            "selected_edge": None,
            "reason": "ambiguous_route",
            "exception_mapping": {
                "intent_key": "AMBIGUOUS_ROUTE",
                "sink_node": "n_exc_ambiguous_route",
            },
            "schema_version": "route_record_v1",
        }
        self._validate(record)

    def test_wrong_schema_version_rejected(self):
        record = {
            "gateway_id": "n1",
            "outgoing_edge_set": [],
            "normalized_conditions": [],
            "predicate_results": [],
            "selected_edge": None,
            "reason": "no_route",
            "exception_mapping": None,
            "schema_version": "route_record_v2",
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(record)

    def test_invalid_reason_rejected(self):
        record = {
            "gateway_id": "n1",
            "outgoing_edge_set": [],
            "normalized_conditions": [],
            "predicate_results": [],
            "selected_edge": None,
            "reason": "magic_guess",
            "exception_mapping": None,
            "schema_version": "route_record_v1",
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(record)

    def test_route_record_dataclass_to_dict(self):
        """RouteRecord.to_dict() output validates against schema."""
        from src.agent.router import RouteRecord

        rr = RouteRecord(
            gateway_id="n8",
            outgoing_edge_set=[{"to": "n9", "raw_condition": None}],
            normalized_conditions=[
                {"to": "n9", "raw_condition": None, "normalized_condition": None}
            ],
            predicate_results=[
                {"to": "n9", "normalized_condition": None,
                 "matched": None, "phase": "fallback"}
            ],
            selected_edge={"to": "n9", "condition": None},
            reason="single_edge",
            exception_mapping=None,
        )
        self._validate(rr.to_dict())


# -----------------------------------------------------------------------
# Gold Record
# -----------------------------------------------------------------------

class TestGoldRecordSchema:
    """Validate gold_record_v1.json against the actual JSONL corpus."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("gold_record_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_all_gold_records_validate(self):
        """Every record in datasets/expected.jsonl must validate."""
        jsonl_path = Path(__file__).resolve().parent.parent / "datasets" / "expected.jsonl"
        with open(jsonl_path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) >= 100, f"Expected >=100 gold records, got {len(records)}"
        errors = []
        for i, rec in enumerate(records):
            try:
                self._validate(rec)
            except jsonschema.ValidationError as e:
                errors.append(
                    f"Record {i} ({rec.get('invoice_id', '?')}): {e.message}"
                )
        assert not errors, f"{len(errors)} records failed validation:\n" + "\n".join(errors)

    def test_minimal_gold_record(self):
        """Minimal valid gold record with required fields only."""
        rec = {
            "invoice_id": "INV-TEST",
            "file": "test.txt",
            "po_match": True,
            "expected_status": ["APPROVED"],
            "expected_fields": {
                "vendor": "Test Corp",
                "amount": 100.0,
                "has_po": True,
            },
            "mock_extraction": {
                "vendor": {"value": "Test Corp", "evidence": "Test Corp"},
                "amount": {"value": 100.0, "evidence": "Total: 100.00"},
                "has_po": {"value": True, "evidence": "PO: PO-1"},
            },
            "tags": ["happy_path"],
        }
        self._validate(rec)

    def test_gold_record_with_optional_fields(self):
        """Gold record with invoice_date and tax_amount."""
        rec = {
            "invoice_id": "INV-TEST-OPT",
            "file": "test_opt.txt",
            "po_match": True,
            "expected_status": ["APPROVED"],
            "expected_fields": {
                "vendor": "Test Corp",
                "amount": 100.0,
                "has_po": True,
                "invoice_date": "2024-01-15",
                "tax_amount": 8.50,
            },
            "mock_extraction": {
                "vendor": {"value": "Test Corp", "evidence": "Test Corp"},
                "amount": {"value": 100.0, "evidence": "Total: 100.00"},
                "has_po": {"value": True, "evidence": "PO: PO-1"},
                "invoice_date": {"value": "2024-01-15", "evidence": "Date: Jan 15"},
                "tax_amount": {"value": 8.50, "evidence": "Tax: $8.50"},
            },
            "tags": ["happy_path"],
        }
        self._validate(rec)

    def test_gold_record_with_documented_optional_keys(self):
        """Gold record with expected_trace, expected_failures, notes."""
        rec = {
            "invoice_id": "INV-TEST-FULL",
            "file": "test_full.txt",
            "po_match": False,
            "expected_status": ["EXCEPTION_NO_PO"],
            "expected_fields": {
                "vendor": "Test Corp",
                "amount": 100.0,
                "has_po": False,
            },
            "mock_extraction": {
                "vendor": {"value": "Test Corp", "evidence": "Test Corp"},
                "amount": {"value": 100.0, "evidence": "Total: 100.00"},
                "has_po": {"value": False, "evidence": ""},
            },
            "tags": ["no_po"],
            "expected_trace": {
                "must_include": ["ENTER_RECORD"],
                "must_exclude": ["APPROVE"],
            },
            "expected_failures": ["PO_PATTERN_MISSING"],
            "notes": "Test case for no-PO path.",
        }
        self._validate(rec)

    def test_empty_expected_status_rejected(self):
        """expected_status must be non-empty list."""
        rec = {
            "invoice_id": "INV-BAD",
            "file": "bad.txt",
            "po_match": True,
            "expected_status": [],
            "expected_fields": {"vendor": "X", "amount": 1.0, "has_po": True},
            "mock_extraction": {
                "vendor": {"value": "X", "evidence": "X"},
                "amount": {"value": 1.0, "evidence": "1.0"},
                "has_po": {"value": True, "evidence": "PO"},
            },
            "tags": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(rec)

    def test_missing_invoice_id_rejected(self):
        rec = {
            "file": "bad.txt",
            "po_match": True,
            "expected_status": ["APPROVED"],
            "expected_fields": {"vendor": "X", "amount": 1.0, "has_po": True},
            "mock_extraction": {
                "vendor": {"value": "X", "evidence": "X"},
                "amount": {"value": 1.0, "evidence": "1.0"},
                "has_po": {"value": True, "evidence": "PO"},
            },
            "tags": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(rec)

    def test_extra_top_level_key_rejected(self):
        rec = {
            "invoice_id": "INV-BAD",
            "file": "bad.txt",
            "po_match": True,
            "expected_status": ["APPROVED"],
            "expected_fields": {"vendor": "X", "amount": 1.0, "has_po": True},
            "mock_extraction": {
                "vendor": {"value": "X", "evidence": "X"},
                "amount": {"value": 1.0, "evidence": "1.0"},
                "has_po": {"value": True, "evidence": "PO"},
            },
            "tags": [],
            "surprise_key": "oops",
        }
        with pytest.raises(jsonschema.ValidationError):
            self._validate(rec)


# -----------------------------------------------------------------------
# Audit Event: extraction
# -----------------------------------------------------------------------

class TestAuditEventExtractionSchema:
    """Validate audit_event_extraction_v1.json — 3 variants via oneOf."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_extraction_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_variant1_llm_error(self):
        """LLM error variant: reasons contains LLM_ERROR."""
        self._validate({
            "node": "ENTER_RECORD",
            "event": "extraction",
            "valid": False,
            "reasons": ["LLM_ERROR"],
        })

    def test_variant2_structural_failure(self):
        """Structural failure: failure_codes with STRUCT_ prefix + status."""
        self._validate({
            "node": "ENTER_RECORD",
            "event": "extraction",
            "valid": False,
            "failure_codes": ["STRUCT_MISSING_KEY", "STRUCT_WRONG_TYPE"],
            "status": "BAD_EXTRACTION",
        })

    def test_variant3_verifier_result_valid(self):
        """Verifier result (valid=true): reasons is empty list."""
        self._validate({
            "node": "ENTER_RECORD",
            "event": "extraction",
            "valid": True,
            "reasons": [],
        })

    def test_variant3_verifier_result_failure(self):
        """Verifier result (valid=false): reasons with failure codes."""
        self._validate({
            "node": "ENTER_RECORD",
            "event": "extraction",
            "valid": False,
            "reasons": ["AMOUNT_MISMATCH", "MISSING_VENDOR"],
        })

    def test_wrong_event_name_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "ENTER_RECORD",
                "event": "not_extraction",
                "valid": True,
                "reasons": [],
            })

    def test_missing_valid_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "ENTER_RECORD",
                "event": "extraction",
                "reasons": [],
            })

    def test_struct_prefix_enforced(self):
        """Variant 2 failure_codes must have STRUCT_ prefix."""
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "ENTER_RECORD",
                "event": "extraction",
                "valid": False,
                "failure_codes": ["AMOUNT_MISMATCH"],
                "status": "BAD_EXTRACTION",
            })

    def test_extra_keys_rejected(self):
        """additionalProperties=false enforced per variant."""
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "ENTER_RECORD",
                "event": "extraction",
                "valid": True,
                "reasons": [],
                "bonus_key": "nope",
            })


# -----------------------------------------------------------------------
# Audit Event: exception_station
# -----------------------------------------------------------------------

class TestAuditEventExceptionStationSchema:
    """Validate audit_event_exception_station_v1.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_exception_station_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_route_for_review_event(self):
        """Standard ROUTE_FOR_REVIEW exception station event."""
        self._validate({
            "event": "exception_station",
            "node": "n_exc_bad_extraction",
            "reason": "BAD_EXTRACTION",
            "gateway": "n3",
        })

    def test_all_reason_values(self):
        """Every known reason value validates."""
        reasons = [
            "BAD_EXTRACTION", "UNMODELED_GATE", "AMBIGUOUS_ROUTE",
            "NO_ROUTE", "NO_PO", "MATCH_FAILED", "UNKNOWN",
        ]
        for reason in reasons:
            self._validate({
                "event": "exception_station",
                "node": f"n_exc_{reason.lower()}",
                "reason": reason,
                "gateway": "n10",
            })

    def test_legacy_manual_review(self):
        """Legacy manual review handler emits exception_station."""
        self._validate({
            "event": "exception_station",
            "node": "MANUAL_REVIEW",
            "reason": "UNKNOWN",
            "gateway": "?",
        })

    def test_invalid_reason_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "exception_station",
                "node": "n_exc_foo",
                "reason": "INVALID_REASON",
                "gateway": "n3",
            })

    def test_missing_gateway_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "exception_station",
                "node": "n_exc_bad_extraction",
                "reason": "BAD_EXTRACTION",
            })


# -----------------------------------------------------------------------
# Audit Event: match_result_set
# -----------------------------------------------------------------------

class TestAuditEventMatchResultSetSchema:
    """Validate audit_event_match_result_set_v1.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_match_result_set_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_match_with_po_match_source(self):
        self._validate({
            "node": "MATCH_3_WAY",
            "event": "match_result_set",
            "match_result": "MATCH",
            "source_flag": "po_match",
        })

    def test_no_match_with_match_3_way_source(self):
        self._validate({
            "node": "MATCH_3_WAY",
            "event": "match_result_set",
            "match_result": "NO_MATCH",
            "source_flag": "match_3_way",
        })

    def test_unknown_with_null_source(self):
        self._validate({
            "node": "MATCH_3_WAY",
            "event": "match_result_set",
            "match_result": "UNKNOWN",
            "source_flag": None,
        })

    def test_all_match_results(self):
        """Every MatchResult value validates."""
        for mr in ["MATCH", "NO_MATCH", "VARIANCE", "UNKNOWN"]:
            self._validate({
                "node": "MATCH_3_WAY",
                "event": "match_result_set",
                "match_result": mr,
                "source_flag": "po_match",
            })

    def test_invalid_match_result_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "MATCH_3_WAY",
                "event": "match_result_set",
                "match_result": "PARTIAL",
                "source_flag": "po_match",
            })

    def test_invalid_source_flag_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "node": "MATCH_3_WAY",
                "event": "match_result_set",
                "match_result": "MATCH",
                "source_flag": "invented_flag",
            })


# -----------------------------------------------------------------------
# Audit Event: route_decision
# -----------------------------------------------------------------------

class TestAuditEventRouteDecisionSchema:
    """Validate audit_event_route_decision_v1.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_route_decision_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_single_edge_route(self):
        self._validate({
            "event": "route_decision",
            "from_node": "n8",
            "candidates": [{"to": "n9", "condition": None, "matched": None}],
            "selected": "n9",
            "reason": "single_edge",
        })

    def test_condition_match_route(self):
        self._validate({
            "event": "route_decision",
            "from_node": "n3",
            "candidates": [
                {"to": "n4", "condition": "has_po == true", "matched": True},
                {"to": "n5", "condition": "has_po == false", "matched": False},
            ],
            "selected": "n4",
            "reason": "condition_match",
        })

    def test_ambiguous_route_null_selected(self):
        self._validate({
            "event": "route_decision",
            "from_node": "n10",
            "candidates": [
                {"to": "n11", "condition": "x == true", "matched": True},
                {"to": "n12", "condition": "y == true", "matched": True},
            ],
            "selected": None,
            "reason": "ambiguous_route",
        })

    def test_all_reason_values(self):
        reasons = [
            "single_edge", "all_same_target", "condition_match",
            "unconditional_fallback", "ambiguous_route", "no_route",
        ]
        for reason in reasons:
            self._validate({
                "event": "route_decision",
                "from_node": "n1",
                "candidates": [],
                "selected": None if reason in ("ambiguous_route", "no_route") else "n2",
                "reason": reason,
            })

    def test_invalid_reason_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "route_decision",
                "from_node": "n1",
                "candidates": [],
                "selected": "n2",
                "reason": "magic_guess",
            })

    def test_missing_from_node_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "route_decision",
                "candidates": [],
                "selected": None,
                "reason": "no_route",
            })

    def test_extra_keys_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "route_decision",
                "from_node": "n1",
                "candidates": [],
                "selected": None,
                "reason": "no_route",
                "bonus": True,
            })


# -----------------------------------------------------------------------
# Audit Event: verifier_summary
# -----------------------------------------------------------------------

class TestAuditEventVerifierSummarySchema:
    """Validate audit_event_verifier_summary_v1.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_verifier_summary_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_valid_extraction_summary(self):
        """Verifier summary for a fully valid extraction."""
        self._validate({
            "event": "verifier_summary",
            "valid": True,
            "failure_codes": [],
            "status_before": "NEW",
            "status_after": "DATA_EXTRACTED",
            "vendor": {"value": "Acme Corp", "ok": True, "has_evidence": True},
            "amount": {"value": 1500.0, "ok": True, "has_evidence": True,
                       "parsed_evidence": 1500.0, "delta": 0.0},
            "has_po": {"value": True, "ok": True, "has_evidence": True},
        })

    def test_failed_extraction_summary(self):
        """Verifier summary with failure codes and bad fields."""
        self._validate({
            "event": "verifier_summary",
            "valid": False,
            "failure_codes": ["AMOUNT_MISMATCH", "MISSING_VENDOR"],
            "status_before": "NEW",
            "status_after": "NEEDS_RETRY",
            "vendor": {"value": None, "ok": False, "has_evidence": False},
            "amount": {"value": 999.0, "ok": False, "has_evidence": True,
                       "parsed_evidence": 500.0, "delta": 499.0},
            "has_po": {"value": True, "ok": True, "has_evidence": True},
        })

    def test_critic_retry_summary(self):
        """Verifier summary emitted by CRITIC_RETRY (same shape)."""
        self._validate({
            "event": "verifier_summary",
            "valid": True,
            "failure_codes": [],
            "status_before": "NEEDS_RETRY",
            "status_after": "DATA_EXTRACTED",
            "vendor": {"value": "Acme Corp", "ok": True, "has_evidence": True},
            "amount": {"value": 100.0, "ok": True, "has_evidence": True,
                       "parsed_evidence": 100.0, "delta": 0.0},
            "has_po": {"value": False, "ok": True, "has_evidence": False},
        })

    def test_null_parsed_evidence_and_delta(self):
        """Amount summary with null parsed_evidence and delta."""
        self._validate({
            "event": "verifier_summary",
            "valid": False,
            "failure_codes": ["EVIDENCE_NOT_FOUND"],
            "status_before": "NEW",
            "status_after": "NEEDS_RETRY",
            "vendor": {"value": "X", "ok": True, "has_evidence": True},
            "amount": {"value": 100.0, "ok": False, "has_evidence": False,
                       "parsed_evidence": None, "delta": None},
            "has_po": {"value": True, "ok": True, "has_evidence": True},
        })

    def test_missing_amount_field_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "verifier_summary",
                "valid": True,
                "failure_codes": [],
                "status_before": "NEW",
                "status_after": "DATA_EXTRACTED",
                "vendor": {"value": "X", "ok": True, "has_evidence": True},
                "has_po": {"value": True, "ok": True, "has_evidence": True},
            })

    def test_amount_missing_delta_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "verifier_summary",
                "valid": True,
                "failure_codes": [],
                "status_before": "NEW",
                "status_after": "DATA_EXTRACTED",
                "vendor": {"value": "X", "ok": True, "has_evidence": True},
                "amount": {"value": 100.0, "ok": True, "has_evidence": True,
                           "parsed_evidence": 100.0},
                "has_po": {"value": True, "ok": True, "has_evidence": True},
            })

    def test_extra_keys_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "verifier_summary",
                "valid": True,
                "failure_codes": [],
                "status_before": "NEW",
                "status_after": "DATA_EXTRACTED",
                "vendor": {"value": "X", "ok": True, "has_evidence": True},
                "amount": {"value": 100.0, "ok": True, "has_evidence": True,
                           "parsed_evidence": 100.0, "delta": 0.0},
                "has_po": {"value": True, "ok": True, "has_evidence": True},
                "bonus": "nope",
            })


# -----------------------------------------------------------------------
# Audit Event: critic_retry_executed
# -----------------------------------------------------------------------

class TestAuditEventCriticRetrySchema:
    """Validate audit_event_critic_retry_v1.json — 3 variants via oneOf."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_critic_retry_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_variant1_llm_error(self):
        self._validate({
            "event": "critic_retry_executed",
            "node": "CRITIC_RETRY",
            "attempt": 1,
            "valid": False,
            "failure_codes": ["LLM_ERROR"],
            "status": "BAD_EXTRACTION",
        })

    def test_variant2_structural_failure(self):
        self._validate({
            "event": "critic_retry_executed",
            "node": "CRITIC_RETRY",
            "attempt": 2,
            "valid": False,
            "failure_codes": ["STRUCT_MISSING_KEY"],
            "status": "BAD_EXTRACTION",
        })

    def test_variant3_verifier_success(self):
        self._validate({
            "event": "critic_retry_executed",
            "node": "CRITIC_RETRY",
            "attempt": 1,
            "valid": True,
            "failure_codes": [],
            "status": "DATA_EXTRACTED",
        })

    def test_variant3_verifier_failure(self):
        self._validate({
            "event": "critic_retry_executed",
            "node": "CRITIC_RETRY",
            "attempt": 1,
            "valid": False,
            "failure_codes": ["AMOUNT_MISMATCH", "MISSING_VENDOR"],
            "status": "BAD_EXTRACTION",
        })

    def test_missing_attempt_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "critic_retry_executed",
                "node": "CRITIC_RETRY",
                "valid": False,
                "failure_codes": ["LLM_ERROR"],
                "status": "BAD_EXTRACTION",
            })

    def test_extra_keys_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "critic_retry_executed",
                "node": "CRITIC_RETRY",
                "attempt": 1,
                "valid": True,
                "failure_codes": [],
                "status": "DATA_EXTRACTED",
                "bonus": True,
            })

    def test_wrong_node_rejected(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "critic_retry_executed",
                "node": "ENTER_RECORD",
                "attempt": 1,
                "valid": True,
                "failure_codes": [],
                "status": "DATA_EXTRACTED",
            })


# -----------------------------------------------------------------------
# Audit Event: arithmetic_check
# -----------------------------------------------------------------------

class TestAuditEventArithmeticCheckSchema:
    """Validate audit_event_arithmetic_check_v1.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_arithmetic_check_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_pass_total_sum_only(self):
        self._validate({
            "event": "arithmetic_check",
            "checks_run": ["total_sum"],
            "passed": True,
            "codes": [],
            "total_sum": {
                "subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                "expected": 447.0, "actual": 447.0, "delta": 0.0,
            },
            "tax_rate": None,
        })

    def test_pass_tax_rate_only(self):
        self._validate({
            "event": "arithmetic_check",
            "checks_run": ["tax_rate"],
            "passed": True,
            "codes": [],
            "total_sum": None,
            "tax_rate": {
                "rate_pct": 8.0, "computed": 32.0, "stated": 32.0, "delta": 0.0,
            },
        })

    def test_pass_both_checks(self):
        self._validate({
            "event": "arithmetic_check",
            "checks_run": ["total_sum", "tax_rate"],
            "passed": True,
            "codes": [],
            "total_sum": {
                "subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                "expected": 447.0, "actual": 447.0, "delta": 0.0,
            },
            "tax_rate": {
                "rate_pct": 8.0, "computed": 32.0, "stated": 32.0, "delta": 0.0,
            },
        })

    def test_fail_total_mismatch(self):
        self._validate({
            "event": "arithmetic_check",
            "checks_run": ["total_sum"],
            "passed": False,
            "codes": ["ARITH_TOTAL_MISMATCH"],
            "total_sum": {
                "subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                "expected": 447.0, "actual": 747.0, "delta": 300.0,
            },
            "tax_rate": None,
        })

    def test_fail_tax_rate_mismatch(self):
        self._validate({
            "event": "arithmetic_check",
            "checks_run": ["total_sum", "tax_rate"],
            "passed": False,
            "codes": ["ARITH_TAX_RATE_MISMATCH"],
            "total_sum": {
                "subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                "expected": 447.0, "actual": 447.0, "delta": 0.0,
            },
            "tax_rate": {
                "rate_pct": 10.0, "computed": 40.0, "stated": 32.0, "delta": 8.0,
            },
        })

    def test_rejects_unknown_code(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "arithmetic_check",
                "checks_run": ["total_sum"],
                "passed": False,
                "codes": ["ARITH_FAKE"],
                "total_sum": None,
            })

    def test_rejects_unknown_check_name(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "arithmetic_check",
                "checks_run": ["unknown"],
                "passed": True,
                "codes": [],
            })

    def test_rejects_missing_required_field(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "arithmetic_check",
                "checks_run": ["total_sum"],
                "codes": [],
            })

    def test_rejects_extra_top_level_key(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({
                "event": "arithmetic_check",
                "checks_run": ["total_sum"],
                "passed": True,
                "codes": [],
                "unexpected": 123,
            })

    def test_cross_layer_schema_parser_explanation(self):
        """Full pipeline: schema-valid payload -> parse_audit_log -> build_explanation."""
        from src.audit_parser import parse_audit_log
        from src.explanation import build_explanation

        payload = {
            "event": "arithmetic_check",
            "checks_run": ["total_sum", "tax_rate"],
            "passed": False,
            "codes": ["ARITH_TOTAL_MISMATCH"],
            "total_sum": {
                "subtotal": 400.0, "taxes": 32.0, "fees": 15.0,
                "expected": 447.0, "actual": 747.0, "delta": 300.0,
            },
            "tax_rate": {
                "rate_pct": 8.0, "computed": 32.0, "stated": 32.0, "delta": 0.0,
            },
        }
        # Schema validates
        self._validate(payload)

        # Parser round-trip
        parsed = parse_audit_log([json.dumps(payload)])
        assert parsed.last_arithmetic_check is not None
        ac = parsed.last_arithmetic_check
        assert ac.passed is False
        assert "ARITH_TOTAL_MISMATCH" in ac.codes
        assert ac.total_sum["delta"] == 300.0

        # Explanation round-trip
        report = build_explanation(parsed, final_status="BAD_EXTRACTION")
        assert report.arithmetic is not None
        assert report.arithmetic.passed is False
        assert "ARITH_TOTAL_MISMATCH" in report.arithmetic.failure_codes
        assert report.arithmetic.total_sum_delta == 300.0
        assert report.arithmetic.tax_rate_delta == 0.0


# -----------------------------------------------------------------------
# Audit Event: route_record wrapper
# -----------------------------------------------------------------------

def _make_route_record_wrapper(*, reason="condition_match", selected_edge=None,
                                exception_mapping=None, edges=None):
    """Build a representative route_record audit event wrapper payload."""
    if edges is None:
        edges = [
            {"to": "n4", "raw_condition": "has_po == true"},
            {"to": "n5", "raw_condition": "has_po == false"},
        ]
    if selected_edge is None and reason not in ("ambiguous_route", "no_route"):
        selected_edge = {"to": edges[0]["to"], "condition": edges[0]["raw_condition"]}
    return {
        "event": "route_record",
        "route_record": {
            "gateway_id": "n3",
            "outgoing_edge_set": edges,
            "normalized_conditions": [
                {**e, "normalized_condition": e["raw_condition"]} for e in edges
            ],
            "predicate_results": [
                {"to": e["to"], "normalized_condition": e["raw_condition"],
                 "matched": i == 0, "phase": "conditional"}
                for i, e in enumerate(edges)
            ],
            "selected_edge": selected_edge,
            "reason": reason,
            "exception_mapping": exception_mapping,
            "schema_version": "route_record_v1",
        },
    }


class TestAuditEventRouteRecordWrapperSchema:
    """Validate audit_event_route_record_v1.json — wrapper around RouteRecord."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_route_record_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def test_schema_is_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_valid_condition_match(self):
        self._validate(_make_route_record_wrapper(reason="condition_match"))

    def test_valid_single_edge(self):
        edge = [{"to": "n5", "raw_condition": None}]
        self._validate(_make_route_record_wrapper(
            reason="single_edge",
            edges=edge,
            selected_edge={"to": "n5", "condition": None},
        ))

    def test_valid_exception_mapping(self):
        self._validate(_make_route_record_wrapper(
            reason="ambiguous_route",
            selected_edge=None,
            exception_mapping={"intent_key": "AMBIGUOUS_ROUTE", "sink_node": "n_exc_ambiguous"},
        ))

    def test_rejects_wrong_event_name(self):
        payload = _make_route_record_wrapper()
        payload["event"] = "route_decision"
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_rejects_missing_route_record(self):
        with pytest.raises(jsonschema.ValidationError):
            self._validate({"event": "route_record"})

    def test_rejects_invalid_nested_reason(self):
        payload = _make_route_record_wrapper()
        payload["route_record"]["reason"] = "fake_reason"
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_rejects_extra_top_level_key(self):
        payload = _make_route_record_wrapper()
        payload["extra"] = 1
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_rejects_nested_extra_key(self):
        payload = _make_route_record_wrapper()
        payload["route_record"]["bonus"] = True
        with pytest.raises(jsonschema.ValidationError):
            self._validate(payload)

    def test_cross_layer_schema_parser(self):
        """Full pipeline: schema-valid wrapper -> parse_audit_log -> RouteRecordEvent."""
        from src.audit_parser import RouteRecordEvent, parse_audit_log

        payload = _make_route_record_wrapper(reason="condition_match")
        self._validate(payload)

        parsed = parse_audit_log([json.dumps(payload)])
        assert len(parsed.route_records) == 1
        rr = parsed.route_records[0]
        assert isinstance(rr, RouteRecordEvent)
        assert rr.route_record["gateway_id"] == "n3"
        assert rr.route_record["reason"] == "condition_match"
        assert rr.route_record["selected_edge"]["to"] == "n4"
        assert rr.route_record["schema_version"] == "route_record_v1"


# -----------------------------------------------------------------------
# Grounding: verifier_summary emitted by execute_node()
# -----------------------------------------------------------------------

class TestVerifierSummaryRoundTrip:
    """Validate that verifier_summary events emitted by real execute_node()
    calls conform to the schema — grounding in actual runtime payloads."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.schema = _load_schema("audit_event_verifier_summary_v1.json")

    def _validate(self, instance):
        jsonschema.validate(instance, self.schema)

    def _extract_event(self, audit_log, event_name):
        for entry in audit_log:
            parsed = json.loads(entry)
            if parsed.get("event") == event_name:
                return parsed
        return None

    def test_enter_record_verifier_summary_validates(self):
        """verifier_summary from ENTER_RECORD with well-formed extraction."""
        from unittest.mock import patch as mock_patch
        from src.agent.nodes import execute_node
        from src.agent.state import make_initial_state

        raw_text = "INVOICE #001\nVendor: Test Vendor\nTotal: $250.00\nPO: PO-1122"
        state = make_initial_state(
            invoice_id="INV-SCHEMA-TEST", raw_text=raw_text, po_match=True,
        )
        extraction = {
            "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
            "amount": {"value": 250.0, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        node = {
            "id": "n_test", "name": "Enter Record",
            "action": {"type": "ENTER_RECORD"},
            "decision": None, "actors": [], "artifacts": [],
        }
        with mock_patch("src.agent.nodes._call_llm_json", return_value=extraction):
            updates = execute_node(state, node)

        summary = self._extract_event(updates["audit_log"], "verifier_summary")
        assert summary is not None, "verifier_summary not found in audit_log"
        self._validate(summary)

    def test_critic_retry_verifier_summary_validates(self):
        """verifier_summary from CRITIC_RETRY with well-formed extraction."""
        from unittest.mock import patch as mock_patch
        from src.agent.nodes import execute_node
        from src.agent.state import make_initial_state

        raw_text = "INVOICE #001\nVendor: Test Vendor\nTotal: $250.00\nPO: PO-1122"
        state = make_initial_state(
            invoice_id="INV-SCHEMA-TEST", raw_text=raw_text, po_match=True,
        )
        state["status"] = "NEEDS_RETRY"
        state["retry_count"] = 0
        state["failure_codes"] = ["AMOUNT_MISMATCH"]
        state["extraction"] = {
            "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
            "amount": {"value": 999.0, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        good_extraction = {
            "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
            "amount": {"value": 250.0, "evidence": "Total: $250.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1122"},
        }
        node = {
            "id": "n_critic", "name": "Critic Retry",
            "action": {"type": "CRITIC_RETRY"},
            "decision": None, "actors": [], "artifacts": [],
        }
        with mock_patch("src.agent.nodes._call_llm_json", return_value=good_extraction):
            updates = execute_node(state, node)

        summary = self._extract_event(updates["audit_log"], "verifier_summary")
        assert summary is not None, "verifier_summary not found in audit_log"
        self._validate(summary)


# -----------------------------------------------------------------------
# UI Audit compatibility: schema-backed events consumable by parsers
# -----------------------------------------------------------------------

class TestSchemaUiAuditCompatibility:
    """Verify that schema-valid event payloads are correctly consumed
    by the existing ui_audit.py extract_* functions."""

    def test_extraction_event_consumed_by_extract_verifier_event(self):
        """Schema-valid extraction event is found by extract_verifier_event."""
        from src.ui_audit import extract_verifier_event

        event = json.dumps({
            "node": "ENTER_RECORD",
            "event": "extraction",
            "valid": True,
            "reasons": [],
        })
        result = extract_verifier_event([event])
        assert result is not None
        assert result["event"] == "extraction"
        assert result["valid"] is True

    def test_exception_station_event_consumed_by_extract_exception_event(self):
        """Schema-valid exception_station event is found by extract_exception_event."""
        from src.ui_audit import extract_exception_event

        event = json.dumps({
            "event": "exception_station",
            "node": "n_exc_bad_extraction",
            "reason": "BAD_EXTRACTION",
            "gateway": "n3",
        })
        result = extract_exception_event([event])
        assert result is not None
        assert result["reason"] == "BAD_EXTRACTION"

    def test_match_result_set_consumed_by_extract_match_event(self):
        """Schema-valid match_result_set event is found by extract_match_event."""
        from src.ui_audit import extract_match_event

        event = json.dumps({
            "node": "MATCH_3_WAY",
            "event": "match_result_set",
            "match_result": "MATCH",
            "source_flag": "po_match",
        })
        result = extract_match_event([event])
        assert result is not None
        assert result["match_result"] == "MATCH"

    def test_route_decision_consumed_by_extract_router_events(self):
        """Schema-valid route_decision event is found by extract_router_events."""
        from src.ui_audit import extract_router_events

        event = json.dumps({
            "event": "route_decision",
            "from_node": "n3",
            "candidates": [
                {"to": "n4", "condition": "has_po == true", "matched": True},
            ],
            "selected": "n4",
            "reason": "condition_match",
        })
        results = extract_router_events([event])
        assert len(results) == 1
        assert results[0]["event"] == "route_decision"
        assert results[0]["from_node"] == "n3"
