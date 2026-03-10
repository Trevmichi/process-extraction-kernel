"""
tests/test_llm_boundary.py
Integration tests for structural validation of LLM extraction payloads.

Verifies that malformed LLM responses are caught by
validate_extraction_structure() before reaching the verifier, producing
STRUCT_* failure codes and BAD_EXTRACTION status.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.agent.nodes import execute_node
from src.agent.state import make_initial_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RAW_TEXT = "INVOICE #001\nVendor: Test Vendor\nTotal: $250.00\nPO: PO-1122"

_WELL_FORMED = {
    "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
    "amount": {"value": 250.0, "evidence": "Total: $250.00"},
    "has_po": {"value": True, "evidence": "PO: PO-1122"},
}

_ENTER_RECORD_NODE = {
    "id": "n_test_enter",
    "name": "Enter Record",
    "action": {"type": "ENTER_RECORD"},
    "decision": None,
    "actors": ["role_ap_clerk"],
    "artifacts": ["art_invoice"],
}

_CRITIC_RETRY_NODE = {
    "id": "n_test_critic",
    "name": "Critic Retry",
    "action": {"type": "CRITIC_RETRY"},
    "decision": None,
    "actors": ["role_ap_clerk"],
    "artifacts": ["art_invoice"],
}


def _make_state(**overrides) -> dict:
    state = make_initial_state(
        invoice_id="INV-BOUNDARY",
        raw_text=_RAW_TEXT,
        po_match=True,
    )
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# ENTER_RECORD: malformed response tests
# ---------------------------------------------------------------------------

class TestEnterRecordMalformed:
    """Structural validation in ENTER_RECORD handler."""

    def test_flat_dict_produces_bad_extraction(self) -> None:
        """Flat dict (not nested {value, evidence}) → BAD_EXTRACTION."""
        malformed = {"vendor": "Acme", "amount": 100, "has_po": True}
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert any(c.startswith("STRUCT_") for c in result["failure_codes"])

    def test_missing_field_produces_bad_extraction(self) -> None:
        """Missing required field → BAD_EXTRACTION with STRUCT_MISSING_*."""
        malformed = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": 100, "evidence": "Total: $100"},
            # has_po missing
        }
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert "STRUCT_MISSING_HAS_PO" in result["failure_codes"]

    def test_structural_failure_skips_retry(self) -> None:
        """Malformed response at retry_count=0 → BAD_EXTRACTION (not NEEDS_RETRY)."""
        malformed = {"vendor": "string", "amount": 100, "has_po": True}
        state = _make_state(retry_count=0)
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(state, _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"

    def test_well_formed_calls_verifier(self) -> None:
        """Well-formed response → verifier is called, status reflects verifier."""
        with patch("src.agent.nodes._call_llm_json", return_value=_WELL_FORMED):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        # Verifier should pass with well-formed + matching evidence
        assert result["status"] == "DATA_EXTRACTED"
        assert result["failure_codes"] == []

    def test_malformed_audit_uses_standard_shape(self) -> None:
        """Malformed response audit entry uses standard keys."""
        malformed = {}
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        audit_log = result["audit_log"]
        assert len(audit_log) >= 1
        entry = json.loads(audit_log[0])
        assert entry["event"] == "extraction"
        assert entry["node"] == "ENTER_RECORD"
        assert entry["valid"] is False
        assert "failure_codes" in entry
        assert "status" in entry

    def test_structural_codes_all_prefixed(self) -> None:
        """All failure codes from malformed response start with STRUCT_."""
        malformed = {"vendor": 42, "amount": "bad"}
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        for code in result["failure_codes"]:
            assert code.startswith("STRUCT_"), f"Non-structural code: {code!r}"


# ---------------------------------------------------------------------------
# CRITIC_RETRY: malformed response tests
# ---------------------------------------------------------------------------

class TestCriticRetryMalformed:
    """Structural validation in CRITIC_RETRY handler."""

    def test_malformed_produces_bad_extraction(self) -> None:
        """Malformed CRITIC_RETRY response → BAD_EXTRACTION with STRUCT_* codes."""
        malformed = {"vendor": "flat_string"}
        state = _make_state(
            retry_count=0,
            failure_codes=["EVIDENCE_NOT_FOUND"],
            extraction=_WELL_FORMED,
        )
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(state, _CRITIC_RETRY_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert any(c.startswith("STRUCT_") for c in result["failure_codes"])

    def test_malformed_audit_reuses_critic_event_shape(self) -> None:
        """Malformed CRITIC_RETRY audit uses critic_retry_executed event shape."""
        malformed = {}
        state = _make_state(
            retry_count=0,
            failure_codes=["MISSING_KEY"],
            extraction={},
        )
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(state, _CRITIC_RETRY_NODE)
        audit_log = result["audit_log"]
        assert len(audit_log) >= 1
        entry = json.loads(audit_log[0])
        assert entry["event"] == "critic_retry_executed"
        assert entry["node"] == "CRITIC_RETRY"
        assert entry["valid"] is False
        assert "attempt" in entry
        assert "failure_codes" in entry
        assert "status" in entry

    def test_well_formed_calls_verifier(self) -> None:
        """Well-formed CRITIC_RETRY response → verifier runs."""
        state = _make_state(
            retry_count=0,
            failure_codes=["EVIDENCE_NOT_FOUND"],
            extraction=_WELL_FORMED,
        )
        with patch("src.agent.nodes._call_llm_json", return_value=_WELL_FORMED):
            result = execute_node(state, _CRITIC_RETRY_NODE)
        assert result["status"] == "DATA_EXTRACTED"


# ---------------------------------------------------------------------------
# Separation principle: STRUCT_* vs verifier codes never mix
# ---------------------------------------------------------------------------

class TestCodeFamilySeparation:
    """Verify that STRUCT_* codes and verifier codes never appear together."""

    def test_malformed_has_only_structural_codes(self) -> None:
        malformed = {"vendor": 42, "amount": "bad", "has_po": []}
        with patch("src.agent.nodes._call_llm_json", return_value=malformed):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        for code in result["failure_codes"]:
            assert code.startswith("STRUCT_"), f"Expected only STRUCT_* codes, got: {code!r}"

    def test_verifier_rejection_has_no_structural_codes(self) -> None:
        """Verifier rejection → no STRUCT_* codes in failure_codes."""
        bad_evidence = {
            "vendor": {"value": "Acme", "evidence": "FABRICATED_VENDOR"},
            "amount": {"value": 999.0, "evidence": "FABRICATED_AMOUNT"},
            "has_po": {"value": True, "evidence": "FABRICATED_PO"},
        }
        with patch("src.agent.nodes._call_llm_json", return_value=bad_evidence):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        for code in result.get("failure_codes", []):
            assert not code.startswith("STRUCT_"), f"Unexpected structural code: {code!r}"


# ---------------------------------------------------------------------------
# Semantic validation (SEM_* codes) integration through execute_node
# ---------------------------------------------------------------------------

class TestSemanticValidation:
    """Semantic plausibility checks in ENTER_RECORD handler."""

    def test_string_amount_produces_bad_extraction(self) -> None:
        """Non-numeric amount → BAD_EXTRACTION with SEM_AMOUNT_NOT_NUMERIC."""
        bad_payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": "banana", "evidence": "Total: banana"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        with patch("src.agent.nodes._call_llm_json", return_value=bad_payload):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert "SEM_AMOUNT_NOT_NUMERIC" in result["failure_codes"]

    def test_empty_vendor_produces_bad_extraction(self) -> None:
        """Empty vendor string → BAD_EXTRACTION with SEM_VENDOR_EMPTY."""
        bad_payload = {
            "vendor": {"value": "", "evidence": "Vendor: "},
            "amount": {"value": 100.0, "evidence": "Total: $100.00"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        with patch("src.agent.nodes._call_llm_json", return_value=bad_payload):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert "SEM_VENDOR_EMPTY" in result["failure_codes"]

    def test_semantic_codes_never_mixed_with_structural(self) -> None:
        """SEM_* rejection produces only SEM_* codes, no STRUCT_* codes."""
        bad_payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": "not_a_number", "evidence": "Total: not_a_number"},
            "has_po": {"value": True, "evidence": "PO: PO-1234"},
        }
        with patch("src.agent.nodes._call_llm_json", return_value=bad_payload):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        for code in result["failure_codes"]:
            assert code.startswith("SEM_"), f"Expected only SEM_* codes, got: {code!r}"

    def test_semantic_failure_skips_verifier(self) -> None:
        """Semantic failure → no provenance (verifier never runs)."""
        bad_payload = {
            "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
            "amount": {"value": True, "evidence": "Total: True"},
            "has_po": {"value": False, "evidence": ""},
        }
        with patch("src.agent.nodes._call_llm_json", return_value=bad_payload):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "BAD_EXTRACTION"
        assert result["provenance"] == {}


# ---------------------------------------------------------------------------
# Extended field activation (Phase 10d)
# ---------------------------------------------------------------------------

_RAW_TEXT_EXTENDED = (
    "INVOICE\nDate: 01/15/2024\nVendor: Test Vendor\n"
    "PO: PO-ABC\nSubtotal: $200.00\nTax: $50.00\nTotal: $250.00"
)

_FIVE_FIELD_PAYLOAD = {
    "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
    "amount": {"value": 250.0, "evidence": "Total: $250.00"},
    "has_po": {"value": True, "evidence": "PO: PO-ABC"},
    "invoice_date": {"value": "2024-01-15", "evidence": "Date: 01/15/2024"},
    "tax_amount": {"value": 50.0, "evidence": "Tax: $50.00"},
}


class TestExtendedFieldActivation:
    """Phase 10d: invoice_date and tax_amount in the live pipeline."""

    def test_five_field_extraction_valid(self) -> None:
        """5-field payload → DATA_EXTRACTED, state has date/tax."""
        state = make_initial_state(
            invoice_id="INV-EXT",
            raw_text=_RAW_TEXT_EXTENDED,
            po_match=True,
        )
        with patch("src.agent.nodes._call_llm_json", return_value=_FIVE_FIELD_PAYLOAD):
            result = execute_node(state, _ENTER_RECORD_NODE)
        assert result["status"] == "DATA_EXTRACTED"
        assert result["invoice_date"] == "2024-01-15"
        assert abs(result["tax_amount"] - 50.0) < 0.01

    def test_three_field_extraction_still_valid(self) -> None:
        """3-field payload (no date/tax) → DATA_EXTRACTED, optional fields at defaults."""
        with patch("src.agent.nodes._call_llm_json", return_value=_WELL_FORMED):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "DATA_EXTRACTED"
        assert "invoice_date" not in result  # not promoted (absent from extraction)
        assert "tax_amount" not in result

    def test_omitted_optional_fields_still_valid(self) -> None:
        """Omitted optional fields → verifier skips, core fields still valid."""
        # LLM omits invoice_date/tax_amount when not found (per prompt instruction)
        with patch("src.agent.nodes._call_llm_json", return_value=_WELL_FORMED):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        assert result["status"] == "DATA_EXTRACTED"
        assert "invoice_date" not in result  # absent → not promoted
        assert "tax_amount" not in result

    def test_verifier_summary_includes_optional_fields(self) -> None:
        """Verifier summary audit event includes date/tax when processed."""
        state = make_initial_state(
            invoice_id="INV-EXT",
            raw_text=_RAW_TEXT_EXTENDED,
            po_match=True,
        )
        with patch("src.agent.nodes._call_llm_json", return_value=_FIVE_FIELD_PAYLOAD):
            result = execute_node(state, _ENTER_RECORD_NODE)
        # Find verifier_summary in audit_log
        vs = None
        for entry in result["audit_log"]:
            obj = json.loads(entry)
            if obj.get("event") == "verifier_summary":
                vs = obj
                break
        assert vs is not None, "verifier_summary not found in audit_log"
        assert "invoice_date" in vs
        assert vs["invoice_date"]["ok"] is True
        assert "tax_amount" in vs
        assert vs["tax_amount"]["ok"] is True

    def test_verifier_summary_omits_absent_optional_fields(self) -> None:
        """Verifier summary omits date/tax when not in extraction."""
        with patch("src.agent.nodes._call_llm_json", return_value=_WELL_FORMED):
            result = execute_node(_make_state(), _ENTER_RECORD_NODE)
        vs = None
        for entry in result["audit_log"]:
            obj = json.loads(entry)
            if obj.get("event") == "verifier_summary":
                vs = obj
                break
        assert vs is not None
        assert "invoice_date" not in vs
        assert "tax_amount" not in vs
