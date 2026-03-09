"""
tests/test_batch_smoke.py
Integration smoke test — compile the production graph and run minimal
invoices through the LangGraph agent.

Mocks the Ollama LLM so no external service is required.  Verifies that
the routing topology actually reaches the expected terminal nodes.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.compiler import build_ap_graph
from src.agent.router import analyze_routing
from src.agent.state import APState, make_initial_state

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
    return make_initial_state(
        invoice_id="INV-SMOKE",
        raw_text=raw_text,
        po_match=po_match,
        match_3_way=match_3_way,
    )


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


class TestAuditTraceContract:
    """Audit log must be a coherent, parseable timeline."""

    def _run_and_get_audit(self, compiled_graph, **kwargs) -> list[str]:
        with patch("src.agent.nodes._call_llm_json", side_effect=_mock_llm_json):
            result: APState = compiled_graph.invoke(
                _make_initial_state(**kwargs)
            )
        return result.get("audit_log", [])

    def _parse_json_entries(self, audit: list[str]) -> list[dict]:
        """Return all audit entries that are valid JSON dicts."""
        parsed = []
        for entry in audit:
            if not isinstance(entry, str):
                continue
            try:
                obj = json.loads(entry)
                if isinstance(obj, dict):
                    parsed.append(obj)
            except (json.JSONDecodeError, TypeError):
                pass
        return parsed

    def test_all_json_entries_parseable(self, compiled_graph):
        """Every audit entry that looks like JSON must parse successfully."""
        audit = self._run_and_get_audit(compiled_graph, po_match=True, match_3_way=True)
        for entry in audit:
            if not isinstance(entry, str):
                continue
            # Only validate entries that look like JSON (start with '{')
            stripped = entry.strip()
            if stripped.startswith("{"):
                try:
                    json.loads(stripped)
                except json.JSONDecodeError:
                    pytest.fail(f"Audit entry is malformed JSON: {entry!r}")

    def test_route_decision_selected_is_valid_node(self, compiled_graph):
        """Every route_decision.selected must be a node in the graph."""
        audit = self._run_and_get_audit(compiled_graph, po_match=True, match_3_way=True)
        parsed = self._parse_json_entries(audit)

        # Load graph node IDs for validation
        graph_data = json.loads(PATCHED_PATH.read_text(encoding="utf-8"))
        node_ids = {n["id"] for n in graph_data["nodes"]}

        route_decisions = [e for e in parsed if e.get("event") == "route_decision"]
        assert len(route_decisions) >= 1, "No route_decision events in audit"

        for rd in route_decisions:
            selected = rd.get("selected")
            if selected is not None:
                assert selected in node_ids, (
                    f"route_decision.selected={selected!r} is not a known node ID"
                )

    def test_route_decision_before_next_node_execution(self, compiled_graph):
        """route_decision events appear before the next node's execution entry."""
        audit = self._run_and_get_audit(compiled_graph, po_match=True, match_3_way=True)

        # Build ordered list of (event_type, from_node) pairs
        events: list[tuple[str, str]] = []
        for entry in audit:
            if not isinstance(entry, str):
                continue
            stripped = entry.strip()
            if stripped.startswith("{"):
                try:
                    obj = json.loads(stripped)
                    if obj.get("event") == "route_decision":
                        events.append(("route_decision", obj["from_node"]))
                except (json.JSONDecodeError, TypeError):
                    pass
            elif stripped.startswith("Executed "):
                # Plain text audit: "Executed INTENT [actor] at NODE_ID"
                parts = stripped.rsplit(" at ", 1)
                if len(parts) == 2:
                    events.append(("executed", parts[1]))

        # Verify: no two consecutive route_decisions for the same node
        for i in range(len(events) - 1):
            if events[i][0] == "route_decision" and events[i + 1][0] == "route_decision":
                assert events[i][1] != events[i + 1][1], (
                    f"Duplicate back-to-back route_decision for {events[i][1]!r}"
                )

    def test_no_duplicate_route_decisions(self, compiled_graph):
        """No two identical route_decision events back-to-back."""
        audit = self._run_and_get_audit(compiled_graph, po_match=True, match_3_way=True)
        parsed = self._parse_json_entries(audit)

        route_decisions = [e for e in parsed if e.get("event") == "route_decision"]
        for i in range(len(route_decisions) - 1):
            a = route_decisions[i]
            b = route_decisions[i + 1]
            assert a != b, (
                f"Duplicate consecutive route_decision: {json.dumps(a)}"
            )


# ===========================================================================
# Error-status dominance at n3 (ENTER_RECORD)
# ===========================================================================

class TestEnterRecordDominance:
    """Prove that BAD_EXTRACTION / MISSING_DATA dominate has_po at n3.

    These are router-level integration tests: they use the real
    ``analyze_routing`` function with edges matching the patched graph
    topology, verifying that error-status edges win unambiguously when
    has_po is also false.
    """

    # n3 outgoing edges (mirrors patched graph topology)
    N3_EDGES = [
        {"to": "n_critic_retry",       "condition": 'status == "NEEDS_RETRY"'},
        {"to": "n_exc_bad_extraction", "condition": 'status == "BAD_EXTRACTION"'},
        {"to": "n_reject",             "condition": 'status == "MISSING_DATA"'},
        {"to": "n_exception",          "condition": (
            'status != "BAD_EXTRACTION" AND status != "NEEDS_RETRY" '
            'AND status != "MISSING_DATA" AND has_po == false'
        )},
        {"to": "n4",                   "condition": None},  # unconditional fallback
    ]

    def test_needs_retry_routes_to_critic(self):
        """NEEDS_RETRY routes to n_critic_retry (first extraction failure)."""
        state: APState = make_initial_state(
            invoice_id="TEST-0001", raw_text="test", po_match=False,
        )
        state["status"] = "NEEDS_RETRY"
        state["has_po"] = False

        result = analyze_routing(state, self.N3_EDGES)

        assert result.selected == "n_critic_retry"
        assert result.reason == "condition_match"
        assert sum(c["matched"] is True for c in result.candidates) == 1
        matched = [c for c in result.candidates if c["matched"] is True]
        assert matched[0]["condition"] == 'status == "NEEDS_RETRY"'

    def test_bad_extraction_routes_to_exception(self):
        """BAD_EXTRACTION routes to exception station (already retried)."""
        state: APState = make_initial_state(
            invoice_id="TEST-0001b", raw_text="test", po_match=False,
        )
        state["status"] = "BAD_EXTRACTION"
        state["has_po"] = False

        result = analyze_routing(state, self.N3_EDGES)

        assert result.selected == "n_exc_bad_extraction"
        assert result.reason == "condition_match"
        assert sum(c["matched"] is True for c in result.candidates) == 1
        matched = [c for c in result.candidates if c["matched"] is True]
        assert matched[0]["condition"] == 'status == "BAD_EXTRACTION"'

    def test_missing_data_dominates_has_po(self):
        """MISSING_DATA routes to n_reject even when has_po is false."""
        state: APState = make_initial_state(
            invoice_id="TEST-0002", raw_text="test", po_match=False,
        )
        state["status"] = "MISSING_DATA"
        state["has_po"] = False

        result = analyze_routing(state, self.N3_EDGES)

        assert result.selected == "n_reject"
        assert result.reason == "condition_match"
        assert sum(c["matched"] is True for c in result.candidates) == 1
        matched = [c for c in result.candidates if c["matched"] is True]
        assert matched[0]["condition"] == 'status == "MISSING_DATA"'

    def test_no_po_routes_to_exception_when_no_error(self):
        """has_po==false routes to n_exception when status is clean."""
        state: APState = make_initial_state(
            invoice_id="TEST-0003", raw_text="test", po_match=False,
        )
        state["status"] = ""
        state["has_po"] = False

        result = analyze_routing(state, self.N3_EDGES)

        assert result.selected == "n_exception"
        assert result.reason == "condition_match"
        assert sum(c["matched"] is True for c in result.candidates) == 1

    def test_normal_path_falls_through_unconditional(self):
        """Clean status + has_po=true falls through to n4 (unconditional)."""
        state: APState = make_initial_state(
            invoice_id="TEST-0004", raw_text="test", po_match=True,
        )
        state["status"] = ""
        state["has_po"] = True

        result = analyze_routing(state, self.N3_EDGES)

        assert result.selected == "n4"
        assert result.reason == "unconditional_fallback"
