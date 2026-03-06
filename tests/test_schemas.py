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
        """Sanity: enum has exactly 23 codes (matching FailureCode Literal)."""
        assert len(self.schema["enum"]) == 23
