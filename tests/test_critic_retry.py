"""
tests/test_critic_retry.py
Tests for the CRITIC_RETRY node: unit tests for execute_node, normalization
pass tests, and end-to-end integration tests with the compiled graph.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.nodes import execute_node
from src.agent.router import analyze_routing
from src.agent.state import APState, make_initial_state
from src.normalize_graph import wire_critic_retry_route, wire_bad_extraction_route

PATCHED_PATH = Path(__file__).parent.parent / "outputs" / "ap_master_manual_auto_patched.json"


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_GOOD_EXTRACTION = {
    "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
    "amount": {"value": 250.0, "evidence": "Total: $250.00"},
    "has_po": {"value": True, "evidence": "PO: PO-1122"},
}

_BAD_EXTRACTION = {
    "vendor": {"value": "Test Vendor", "evidence": "Vendor: Test Vendor"},
    "amount": {"value": 999.99, "evidence": "Total: $250.00"},  # amount mismatch
    "has_po": {"value": True, "evidence": "PO: PO-1122"},
}

_CRITIC_NODE = {
    "id": "n_critic_retry",
    "kind": "task",
    "name": "Critic Retry",
    "action": {
        "type": "CRITIC_RETRY",
        "actor_id": "role_ap_clerk",
        "artifact_id": "art_invoice",
        "extra": {},
    },
    "decision": None,
    "evidence": [],
    "meta": {"canonical_key": "task:CRITIC_RETRY"},
}

_RAW_TEXT = (
    "INVOICE #001\n"
    "Vendor: Test Vendor\n"
    "Total: $250.00\n"
    "PO: PO-1122"
)


def _make_state(
    *,
    status: str = "NEEDS_RETRY",
    retry_count: int = 0,
    failure_codes: list | None = None,
    extraction: dict | None = None,
    has_po: bool = True,
) -> APState:
    state = make_initial_state(
        invoice_id="TEST-CRITIC", raw_text=_RAW_TEXT, po_match=True,
    )
    state["status"] = status
    state["retry_count"] = retry_count
    state["failure_codes"] = failure_codes or ["AMOUNT_MISMATCH"]
    state["extraction"] = extraction or _BAD_EXTRACTION
    state["has_po"] = has_po
    return state


# ===========================================================================
# Unit tests: execute_node with CRITIC_RETRY intent
# ===========================================================================

class TestCriticRetryNodeExecution:
    """Test execute_node() with a CRITIC_RETRY node dict."""

    def test_critic_corrects_extraction(self):
        """Critic returns valid extraction → status=DATA_EXTRACTED."""
        state = _make_state()

        with patch("src.agent.nodes._call_llm_json", return_value=_GOOD_EXTRACTION):
            updates = execute_node(state, _CRITIC_NODE)

        assert updates["status"] == "DATA_EXTRACTED"
        assert updates["retry_count"] == 1
        assert updates["vendor"] == "Test Vendor"
        assert abs(updates["amount"] - 250.0) < 0.01
        assert updates["has_po"] is True
        assert updates["failure_codes"] == []

    def test_critic_fails_extraction(self):
        """Critic returns still-bad extraction → status=BAD_EXTRACTION."""
        state = _make_state()

        with patch("src.agent.nodes._call_llm_json", return_value=_BAD_EXTRACTION):
            updates = execute_node(state, _CRITIC_NODE)

        assert updates["status"] == "BAD_EXTRACTION"
        assert updates["retry_count"] == 1
        assert len(updates["failure_codes"]) > 0

    def test_critic_llm_error(self):
        """Critic LLM returns error → status=BAD_EXTRACTION, failure_codes=LLM_ERROR."""
        state = _make_state()

        with patch("src.agent.nodes._call_llm_json", return_value={"_error": "connection refused"}):
            updates = execute_node(state, _CRITIC_NODE)

        assert updates["status"] == "BAD_EXTRACTION"
        assert updates["retry_count"] == 1
        assert updates["failure_codes"] == ["LLM_ERROR"]

    def test_critic_emits_audit_events(self):
        """Critic emits critic_retry_executed + verifier_summary + amount_candidates."""
        state = _make_state()

        with patch("src.agent.nodes._call_llm_json", return_value=_GOOD_EXTRACTION):
            updates = execute_node(state, _CRITIC_NODE)

        audit_log = updates.get("audit_log", [])
        events = []
        for entry in audit_log:
            try:
                events.append(json.loads(entry))
            except (json.JSONDecodeError, TypeError):
                pass

        event_types = {e.get("event") for e in events}
        assert "critic_retry_executed" in event_types
        assert "verifier_summary" in event_types
        assert "amount_candidates" in event_types

    def test_critic_increments_retry_count(self):
        """retry_count is incremented regardless of success/failure."""
        state = _make_state(retry_count=0)

        with patch("src.agent.nodes._call_llm_json", return_value=_GOOD_EXTRACTION):
            updates = execute_node(state, _CRITIC_NODE)
        assert updates["retry_count"] == 1

        # Starting from retry_count=5 (edge case)
        state2 = _make_state(retry_count=5)
        with patch("src.agent.nodes._call_llm_json", return_value=_GOOD_EXTRACTION):
            updates2 = execute_node(state2, _CRITIC_NODE)
        assert updates2["retry_count"] == 6

    def test_critic_prompt_includes_failure_codes(self):
        """The critic prompt includes failure codes and previous extraction."""
        state = _make_state(failure_codes=["AMOUNT_MISMATCH", "VENDOR_EVIDENCE_MISMATCH"])
        captured_prompts = []

        def _capture_prompt(prompt):
            captured_prompts.append(prompt)
            return _GOOD_EXTRACTION

        with patch("src.agent.nodes._call_llm_json", side_effect=_capture_prompt):
            execute_node(state, _CRITIC_NODE)

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "AMOUNT_MISMATCH" in prompt
        assert "VENDOR_EVIDENCE_MISMATCH" in prompt
        assert "forensic extraction critic" in prompt.lower()
        # Schema is injected literally
        assert '"vendor"' in prompt
        assert '"amount"' in prompt
        assert '"has_po"' in prompt


# ===========================================================================
# Normalization pass tests
# ===========================================================================

class TestCriticRetryNormalizationPass:
    """Tests for wire_critic_retry_route() normalization pass."""

    def _make_graph(self) -> dict:
        """Build a minimal graph with ENTER_RECORD, CRITIC_RETRY, and exception nodes."""
        return {
            "nodes": [
                {"id": "n3", "kind": "task", "action": {"type": "ENTER_RECORD"}, "meta": {}},
                {"id": "n4", "kind": "task", "action": {"type": "VALIDATE_FIELDS"}, "meta": {}},
                {"id": "n_critic_retry", "kind": "task",
                 "action": {"type": "CRITIC_RETRY"}, "meta": {}},
                {"id": "n_reject", "kind": "task",
                 "action": {"type": "REJECT_INVOICE"}, "meta": {}},
                {"id": "n_exception", "kind": "task",
                 "action": {"type": "MANUAL_REVIEW_NO_PO"}, "meta": {}},
                {"id": "n_exc_bad_extraction", "kind": "task",
                 "action": {"type": "ROUTE_FOR_REVIEW", "extra": {"reason": "BAD_EXTRACTION"}},
                 "meta": {"canonical_key": "task:MANUAL_REVIEW_BAD_EXTRACTION",
                          "intent_key": "task:MANUAL_REVIEW_BAD_EXTRACTION"}},
            ],
            "edges": [
                # Pre-existing BAD_EXTRACTION edge (from wire_bad_extraction_route)
                {"frm": "n3", "to": "n_reject", "condition": 'status == "BAD_EXTRACTION"'},
                # Unconditional fallback
                {"frm": "n3", "to": "n4", "condition": None},
            ],
        }

    def test_wire_critic_retry_creates_edges(self):
        """Pass creates expected edges from n3 and n_critic_retry."""
        data = self._make_graph()
        data, log = wire_critic_retry_route(data)

        edge_keys = [(e["frm"], e["to"], e.get("condition")) for e in data["edges"]]

        # n3 → n_critic_retry
        assert ("n3", "n_critic_retry", 'status == "NEEDS_RETRY"') in edge_keys
        # n3 → n_exc_bad_extraction
        assert ("n3", "n_exc_bad_extraction", 'status == "BAD_EXTRACTION"') in edge_keys
        # n_critic_retry → n_exc_bad_extraction
        assert ("n_critic_retry", "n_exc_bad_extraction", 'status == "BAD_EXTRACTION"') in edge_keys
        # n_critic_retry → n_exception (no-PO guard)
        assert ("n_critic_retry", "n_exception",
                'status != "BAD_EXTRACTION" AND has_po == false') in edge_keys
        # n_critic_retry → n4 (unconditional)
        assert ("n_critic_retry", "n4", None) in edge_keys

    def test_wire_critic_retry_removes_old_bad_extraction_edge(self):
        """Old n3→n_reject BAD_EXTRACTION edge is removed."""
        data = self._make_graph()
        data, log = wire_critic_retry_route(data)

        old_edges = [
            e for e in data["edges"]
            if e.get("frm") == "n3" and e.get("to") == "n_reject"
               and e.get("condition") == 'status == "BAD_EXTRACTION"'
        ]
        assert len(old_edges) == 0

    def test_wire_critic_retry_idempotent(self):
        """Running the pass twice produces the same result."""
        data = self._make_graph()
        data, log1 = wire_critic_retry_route(data)
        edges_after_first = [(e["frm"], e["to"], e.get("condition")) for e in data["edges"]]

        data, log2 = wire_critic_retry_route(data)
        edges_after_second = [(e["frm"], e["to"], e.get("condition")) for e in data["edges"]]

        assert edges_after_first == edges_after_second
        # Second run should skip
        assert any("already present" in line for line in log2)

    def test_skips_when_no_critic_node(self):
        """Pass skips gracefully when CRITIC_RETRY node is absent."""
        data = self._make_graph()
        # Remove the critic node
        data["nodes"] = [n for n in data["nodes"] if n["id"] != "n_critic_retry"]

        data, log = wire_critic_retry_route(data)
        assert any("No CRITIC_RETRY node" in line for line in log)


# ===========================================================================
# Router-level integration tests for n_critic_retry edges
# ===========================================================================

class TestCriticRetryRouting:
    """Verify routing from n_critic_retry matches expected topology."""

    CRITIC_EDGES = [
        {"to": "n_exc_bad_extraction", "condition": 'status == "BAD_EXTRACTION"'},
        {"to": "n_exception",          "condition": 'status != "BAD_EXTRACTION" AND has_po == false'},
        {"to": "n4",                   "condition": None},
    ]

    def test_bad_extraction_routes_to_exception_station(self):
        """BAD_EXTRACTION from critic → n_exc_bad_extraction."""
        state = _make_state(status="BAD_EXTRACTION")
        result = analyze_routing(state, self.CRITIC_EDGES)
        assert result.selected == "n_exc_bad_extraction"
        assert result.reason == "condition_match"

    def test_success_no_po_routes_to_manual_review(self):
        """DATA_EXTRACTED + has_po==false → n_exception (no-PO guard)."""
        state = _make_state(status="DATA_EXTRACTED", has_po=False)
        result = analyze_routing(state, self.CRITIC_EDGES)
        assert result.selected == "n_exception"
        assert result.reason == "condition_match"

    def test_success_with_po_falls_through(self):
        """DATA_EXTRACTED + has_po==true → n4 (unconditional fallback)."""
        state = _make_state(status="DATA_EXTRACTED", has_po=True)
        result = analyze_routing(state, self.CRITIC_EDGES)
        assert result.selected == "n4"
        assert result.reason == "unconditional_fallback"


# ===========================================================================
# End-to-end integration tests with compiled graph
# ===========================================================================

@pytest.fixture(scope="module")
def compiled_graph():
    if not PATCHED_PATH.exists():
        pytest.skip("Patched graph not found — run patch_logic.py first")
    from src.agent.compiler import build_ap_graph
    return build_ap_graph(str(PATCHED_PATH))


class TestCriticRetryEndToEnd:
    """Full graph.invoke() tests with mock LLM."""

    def test_critic_corrects_then_approved(self, compiled_graph):
        """First extraction fails, critic fixes it → APPROVED or PAID."""
        call_count = [0]

        def _mock_llm(prompt: str) -> dict:
            call_count[0] += 1
            if "forensic extraction critic" in prompt.lower():
                # Critic returns good extraction
                return _GOOD_EXTRACTION
            if "data extractor" in prompt.lower():
                # First extraction returns bad amount
                return _BAD_EXTRACTION
            if "validator" in prompt.lower():
                return {"is_valid": True}
            return {}

        state = make_initial_state(
            invoice_id="TEST-E2E-CRITIC-OK",
            raw_text=_RAW_TEXT,
            po_match=True,
            match_3_way=True,
        )

        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm):
            result: APState = compiled_graph.invoke(state)

        status = result.get("status", "")
        assert status in ("APPROVED", "PAID", "ESCALATED"), (
            f"Expected terminal success, got {status!r}\n"
            f"audit_log={json.dumps(result.get('audit_log', []), indent=2)}"
        )
        # Confirm critic was called (at least 2 LLM calls: extractor + critic)
        assert call_count[0] >= 2
        assert result.get("retry_count", 0) == 1

    def test_critic_fails_then_exception_station(self, compiled_graph):
        """Both extraction and critic fail → EXCEPTION_BAD_EXTRACTION."""

        def _mock_llm(prompt: str) -> dict:
            if "data extractor" in prompt.lower() or "forensic extraction critic" in prompt.lower():
                return _BAD_EXTRACTION
            if "validator" in prompt.lower():
                return {"is_valid": True}
            return {}

        state = make_initial_state(
            invoice_id="TEST-E2E-CRITIC-FAIL",
            raw_text=_RAW_TEXT,
            po_match=True,
            match_3_way=True,
        )

        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm):
            result: APState = compiled_graph.invoke(state)

        status = result.get("status", "")
        assert status == "EXCEPTION_BAD_EXTRACTION", (
            f"Expected EXCEPTION_BAD_EXTRACTION, got {status!r}\n"
            f"audit_log={json.dumps(result.get('audit_log', []), indent=2)}"
        )
        assert result.get("retry_count", 0) == 1
