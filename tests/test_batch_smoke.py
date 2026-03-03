"""
tests/test_batch_smoke.py
Integration smoke test — compile the production graph and run minimal
invoices through the LangGraph agent.

Mocks the Ollama LLM so no external service is required.  Verifies that
the routing topology actually reaches the expected terminal nodes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.compiler import build_ap_graph
from src.agent.state import APState

PATCHED_PATH = Path(__file__).parent.parent / "outputs" / "ap_master_manual_auto_patched.json"


# ---------------------------------------------------------------------------
# LLM mock — returns valid extraction / validation results
# ---------------------------------------------------------------------------

def _mock_llm_json(prompt: str) -> dict:
    """Deterministic LLM mock for ENTER_RECORD and VALIDATE_FIELDS."""
    if "data extractor" in prompt.lower():
        return {
            "vendor":  {"value": "Test Vendor",  "evidence": "Vendor: Test Vendor"},
            "amount":  {"value": 250.0,          "evidence": "Total: $250.00"},
            "has_po":  {"value": True,            "evidence": "PO: PO-1122"},
        }
    if "validator" in prompt.lower():
        return {"is_valid": True}
    return {}


def _make_initial_state(
    *,
    po_match: bool = True,
    match_3_way: bool = True,
    amount: float = 250.0,
) -> APState:
    raw_text = (
        "INVOICE #001\n"
        "Vendor: Test Vendor\n"
        f"Total: ${amount:.2f}\n"
        "PO: PO-1122"
    )
    return {
        "invoice_id":   "INV-SMOKE",
        "vendor":       "",
        "amount":       0.0,
        "has_po":       False,
        "po_match":     po_match,
        "match_3_way":  match_3_way,
        "match_result": "UNKNOWN",
        "status":       "NEW",
        "current_node": "",
        "last_gateway": "",
        "audit_log":    [],
        "raw_text":     raw_text,
        "extraction":   {},
        "provenance":   {},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def compiled_graph():
    if not PATCHED_PATH.exists():
        pytest.skip("Patched graph not found — run patch_logic.py first")
    return build_ap_graph(str(PATCHED_PATH))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBatchSmoke:
    """End-to-end smoke tests: compile production graph + run invoices."""

    def test_po_match_true_reaches_approval(self, compiled_graph):
        """Invoice with po_match=True, match_3_way=True → APPROVED or PAID.

        Regression guard: before the n4 fix, match_result stayed UNKNOWN and
        every invoice hit EXCEPTION_UNMODELED_GATE.
        """
        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm_json):
            result: APState = compiled_graph.invoke(
                _make_initial_state(po_match=True, match_3_way=True)
            )

        status = result.get("status", "")
        assert status not in (
            "EXCEPTION_UNMODELED_GATE",
            "EXCEPTION_UNMODELED",
        ), (
            f"Invoice hit unmodeled exception: status={status!r}\n"
            f"audit_log={json.dumps(result.get('audit_log', []), indent=2)}"
        )
        assert status in ("APPROVED", "PAID"), (
            f"Expected APPROVED or PAID, got {status!r}\n"
            f"audit_log={json.dumps(result.get('audit_log', []), indent=2)}"
        )

    def test_po_match_false_reaches_no_match(self, compiled_graph):
        """Invoice with po_match=False → match fails, routes to exception."""
        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm_json):
            result: APState = compiled_graph.invoke(
                _make_initial_state(po_match=False, match_3_way=False)
            )

        status = result.get("status", "")
        assert status != "EXCEPTION_UNMODELED", (
            f"Should route to match-failure, not unmodeled: status={status!r}"
        )
        assert status == "EXCEPTION_MATCH_FAILED", (
            f"Expected EXCEPTION_MATCH_FAILED, got {status!r}\n"
            f"audit_log={json.dumps(result.get('audit_log', []), indent=2)}"
        )

    def test_match_result_set_event_in_audit(self, compiled_graph):
        """MATCH_3_WAY must emit match_result_set event with correct value."""
        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm_json):
            result: APState = compiled_graph.invoke(
                _make_initial_state(po_match=True, match_3_way=True)
            )

        audit = result.get("audit_log", [])
        match_events = []
        for entry in audit:
            if not isinstance(entry, str):
                continue
            try:
                parsed = json.loads(entry)
            except (json.JSONDecodeError, TypeError):
                continue
            if parsed.get("event") == "match_result_set":
                match_events.append(parsed)

        assert len(match_events) >= 1, (
            f"No match_result_set event found in audit_log"
        )
        assert match_events[-1]["match_result"] == "MATCH"
        assert match_events[-1]["source_flag"] == "po_match"

    def test_no_match_result_before_match_decision(self, compiled_graph):
        """match_result must be set (non-UNKNOWN) before any MATCH_DECISION routing.

        Checks by verifying that match_result in final state is not UNKNOWN
        when po_match is explicitly True.
        """
        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm_json):
            result: APState = compiled_graph.invoke(
                _make_initial_state(po_match=True, match_3_way=True)
            )

        assert result.get("match_result") != "UNKNOWN", (
            f"match_result should have been set by MATCH_3_WAY node, "
            f"got UNKNOWN — suggests MATCH_3_WAY never executed"
        )
