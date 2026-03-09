"""
tests/test_schema_validator.py
Unit tests for the runtime JSON Schema validation module.

Covers: validator loading, caching, success/failure paths, error messages,
SchemaValidationError, and edge cases.
"""
from __future__ import annotations

import pytest

from src.schema_validator import (
    SchemaValidationError,
    _VALIDATOR_CACHE,
    _load_validator,
    assert_valid,
    validate_payload,
)


# ---------------------------------------------------------------------------
# Validator loading and caching
# ---------------------------------------------------------------------------

class TestValidatorLoading:

    def test_load_validator_returns_validator(self):
        v = _load_validator("extraction_payload_v1.json")
        assert hasattr(v, "iter_errors")

    def test_load_validator_caches(self):
        v1 = _load_validator("extraction_payload_v1.json")
        v2 = _load_validator("extraction_payload_v1.json")
        assert v1 is v2

    def test_load_validator_different_schemas(self):
        v1 = _load_validator("extraction_payload_v1.json")
        v2 = _load_validator("provenance_report_v1.json")
        assert v1 is not v2

    def test_load_validator_missing_schema_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_validator("nonexistent_schema_v99.json")


# ---------------------------------------------------------------------------
# validate_payload
# ---------------------------------------------------------------------------

class TestValidatePayload:

    def test_valid_extraction_returns_empty(self):
        payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100"},
            "has_po": {"value": True, "evidence": "PO: 123"},
        }
        assert validate_payload(payload, "extraction_payload_v1.json") == []

    def test_invalid_extraction_returns_errors(self):
        payload = {"vendor": "flat_string"}
        errors = validate_payload(payload, "extraction_payload_v1.json")
        assert len(errors) > 0

    def test_error_messages_are_strings(self):
        payload = {}
        errors = validate_payload(payload, "extraction_payload_v1.json")
        assert all(isinstance(e, str) for e in errors)

    def test_valid_provenance_returns_empty(self):
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
        }
        assert validate_payload(prov, "provenance_report_v1.json") == []

    def test_provenance_with_arithmetic_returns_empty(self):
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 10, "match_tier": "exact_match"},
            "amount": {"grounded": True, "parsed_evidence": 100.0, "delta": 0.0,
                       "evidence_found_at": 25, "match_tier": "exact_match"},
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "exact_match"},
            "arithmetic": {
                "checks_run": ["total_sum"],
                "passed": True,
                "codes": [],
                "total_sum": {
                    "subtotal": 90.0, "taxes": 10.0, "fees": 0.0,
                    "expected": 100.0, "actual": 100.0, "delta": 0.0,
                },
            },
        }
        assert validate_payload(prov, "provenance_report_v1.json") == []

    def test_provenance_extra_field_rejected(self):
        prov = {
            "vendor": {"grounded": False, "evidence_found_at": -1, "match_tier": "not_found"},
            "amount": {"grounded": False, "parsed_evidence": None, "delta": None, "match_tier": "not_found"},
            "has_po": {"grounded": False, "po_pattern_found": None, "match_tier": "not_found"},
            "unexpected_field": True,
        }
        errors = validate_payload(prov, "provenance_report_v1.json")
        assert len(errors) > 0

    def test_valid_route_record_returns_empty(self):
        record = {
            "schema_version": "route_record_v1",
            "gateway_id": "n_gw",
            "outgoing_edge_set": [{"to": "n1", "raw_condition": None}],
            "normalized_conditions": [{"to": "n1", "raw_condition": None,
                                       "normalized_condition": None}],
            "predicate_results": [{"to": "n1", "normalized_condition": None,
                                   "matched": None, "phase": "fallback"}],
            "selected_edge": {"to": "n1", "condition": None},
            "reason": "single_edge",
            "exception_mapping": None,
        }
        assert validate_payload(record, "route_record_v1.json") == []


# ---------------------------------------------------------------------------
# assert_valid
# ---------------------------------------------------------------------------

class TestAssertValid:

    def test_valid_payload_does_not_raise(self):
        payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100"},
            "has_po": {"value": True, "evidence": "PO: 123"},
        }
        assert_valid(payload, "extraction_payload_v1.json")  # should not raise

    def test_invalid_payload_raises_schema_validation_error(self):
        with pytest.raises(SchemaValidationError):
            assert_valid({}, "extraction_payload_v1.json")

    def test_schema_validation_error_is_value_error(self):
        with pytest.raises(ValueError):
            assert_valid({}, "extraction_payload_v1.json")

    def test_error_message_includes_schema_name(self):
        with pytest.raises(SchemaValidationError, match="extraction_payload_v1.json"):
            assert_valid({}, "extraction_payload_v1.json")

    def test_provenance_assert_valid_with_arithmetic(self):
        prov = {
            "vendor": {"grounded": True, "evidence_found_at": 5, "match_tier": "normalized_match"},
            "amount": {"grounded": True, "parsed_evidence": 50.0, "delta": 0.0,
                       "evidence_found_at": 20, "match_tier": "exact_match"},
            "has_po": {"grounded": True, "po_pattern_found": True, "match_tier": "exact_match"},
            "arithmetic": {
                "checks_run": ["total_sum", "tax_rate"],
                "passed": False,
                "codes": ["ARITH_TOTAL_SUM_MISMATCH"],
                "total_sum": {
                    "subtotal": 40.0, "taxes": 5.0, "fees": 0.0,
                    "expected": 45.0, "actual": 50.0, "delta": 5.0,
                },
                "tax_rate": {
                    "rate_pct": 10.0, "computed": 4.0, "stated": 5.0, "delta": 1.0,
                },
            },
        }
        assert_valid(prov, "provenance_report_v1.json")  # should not raise


# ---------------------------------------------------------------------------
# End-to-end boundary tests (through real node/router paths)
# ---------------------------------------------------------------------------

class TestBoundaryIntegration:
    """Verify schema validation fires at real emission boundaries."""

    def test_malformed_extraction_triggers_schema_gate(self):
        """Extraction with extra field → SCHEMA_EXTRACTION_INVALID through execute_node."""
        from unittest.mock import patch as mock_patch
        from src.agent.nodes import execute_node
        from src.agent.state import make_initial_state

        # Structurally valid but has an unexpected extra field
        payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100"},
            "has_po": {"value": True, "evidence": "PO: 123"},
            "rogue_field": {"value": "bad", "evidence": "bad"},
        }
        node = {
            "id": "n_test", "name": "Enter Record",
            "action": {"type": "ENTER_RECORD"},
            "decision": None, "actors": ["role_ap_clerk"],
            "artifacts": ["art_invoice"],
        }
        state = make_initial_state(
            invoice_id="INV-SCHEMA", raw_text="INVOICE Vendor: Acme Total: $100 PO: 123",
            po_match=True,
        )
        with mock_patch("src.agent.nodes._call_llm_json", return_value=payload):
            result = execute_node(state, node)

        assert result["status"] == "BAD_EXTRACTION"
        assert "SCHEMA_EXTRACTION_INVALID" in result["failure_codes"]

    def test_critic_retry_schema_gate(self):
        """CRITIC_RETRY with extra field → SCHEMA_EXTRACTION_INVALID."""
        from unittest.mock import patch as mock_patch
        from src.agent.nodes import execute_node
        from src.agent.state import make_initial_state

        payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100.0, "evidence": "Total: $100"},
            "has_po": {"value": True, "evidence": "PO: 123"},
            "rogue_field": {"value": "bad", "evidence": "bad"},
        }
        node = {
            "id": "n_test_critic", "name": "Critic Retry",
            "action": {"type": "CRITIC_RETRY"},
            "decision": None, "actors": ["role_ap_clerk"],
            "artifacts": ["art_invoice"],
        }
        well_formed = {
            "vendor": {"value": "Test", "evidence": "Vendor: Test"},
            "amount": {"value": 100.0, "evidence": "Total: $100"},
            "has_po": {"value": True, "evidence": "PO: 123"},
        }
        state = make_initial_state(
            invoice_id="INV-SCHEMA-CR", raw_text="INVOICE Vendor: Acme Total: $100 PO: 123",
            po_match=True,
        )
        state["retry_count"] = 0
        state["failure_codes"] = ["EVIDENCE_NOT_FOUND"]
        state["extraction"] = well_formed

        with mock_patch("src.agent.nodes._call_llm_json", return_value=payload):
            result = execute_node(state, node)

        assert result["status"] == "BAD_EXTRACTION"
        assert "SCHEMA_EXTRACTION_INVALID" in result["failure_codes"]

    def test_route_record_schema_enforcement(self):
        """build_route_record() output passes schema validation (no crash)."""
        from src.agent.router import RouteResult, build_route_record

        edges = [
            {"to": "n1", "condition": "has_po == true"},
            {"to": "n2", "condition": "has_po == false"},
        ]
        result = RouteResult(
            selected="n1",
            reason="condition_match",
            candidates=[
                {"to": "n1", "condition": "has_po == true", "matched": True},
                {"to": "n2", "condition": "has_po == false", "matched": False},
            ],
        )
        # Should not raise SchemaValidationError
        record = build_route_record(
            gateway_id="n_gw",
            outgoing_edges=edges,
            result=result,
        )
        assert record["schema_version"] == "route_record_v1"
