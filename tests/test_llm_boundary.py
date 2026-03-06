"""
tests/test_llm_boundary.py
Integration tests for structural validation of LLM extraction payloads.

Verifies that malformed LLM responses are caught by
validate_extraction_structure() before reaching the verifier, producing
STRUCT_* failure codes and BAD_EXTRACTION status.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

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
