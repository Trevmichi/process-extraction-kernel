"""
tests/test_state.py
Tests for make_initial_state(), DEFAULT_STATE_TEMPLATE, and REQUIRED_KEYS.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.state import (
    DEFAULT_STATE_TEMPLATE,
    REQUIRED_KEYS,
    make_initial_state,
)


class TestMakeInitialState:

    def test_all_required_keys_present(self):
        """Every key in REQUIRED_KEYS is present in the returned state."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test")
        assert set(state.keys()) == REQUIRED_KEYS

    def test_match_3_way_defaults_to_po_match(self):
        """When match_3_way is not specified, it mirrors po_match."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test", po_match=True)
        assert state["match_3_way"] is True

        state2 = make_initial_state(invoice_id="INV-1", raw_text="test", po_match=False)
        assert state2["match_3_way"] is False

    def test_match_3_way_explicit_override(self):
        """Explicit match_3_way takes precedence over po_match."""
        state = make_initial_state(
            invoice_id="INV-1", raw_text="test",
            po_match=True, match_3_way=False,
        )
        assert state["match_3_way"] is False
        assert state["po_match"] is True

    def test_safe_defaults(self):
        """Non-required fields have expected safe defaults."""
        state = make_initial_state(invoice_id="INV-1", raw_text="hello")
        assert state["invoice_id"] == "INV-1"
        assert state["raw_text"] == "hello"
        assert state["vendor"] == ""
        assert state["amount"] == 0.0
        assert state["has_po"] is False
        assert state["match_result"] == "UNKNOWN"
        assert state["status"] == "NEW"
        assert state["current_node"] == ""
        assert state["last_gateway"] == ""

    def test_fresh_mutables(self):
        """Mutable list/dict fields are fresh per call (not shared)."""
        s1 = make_initial_state(invoice_id="INV-1", raw_text="a")
        s2 = make_initial_state(invoice_id="INV-2", raw_text="b")
        # Must be different objects
        assert s1["audit_log"] is not s2["audit_log"]
        assert s1["route_records"] is not s2["route_records"]
        assert s1["extraction"] is not s2["extraction"]
        assert s1["provenance"] is not s2["provenance"]
        # Mutating one must not affect the other
        s1["audit_log"].append("x")
        s1["route_records"].append({"x": 1})
        assert s2["audit_log"] == []
        assert s2["route_records"] == []


class TestTemplateImmutability:
    """DEFAULT_STATE_TEMPLATE must never be mutated at runtime."""

    def test_template_audit_log_survives_state_mutation(self):
        """Mutating a state's audit_log must not pollute the template."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test")
        state["audit_log"].append("should not appear in template")
        assert DEFAULT_STATE_TEMPLATE["audit_log"] == []

    def test_template_route_records_survives_state_mutation(self):
        """Mutating a state's route_records must not pollute the template."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test")
        state["route_records"].append({"gateway_id": "n1"})
        assert DEFAULT_STATE_TEMPLATE["route_records"] == []

    def test_template_extraction_survives_state_mutation(self):
        """Mutating a state's extraction must not pollute the template."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test")
        state["extraction"]["vendor"] = "ACME"
        assert DEFAULT_STATE_TEMPLATE["extraction"] == {}

    def test_template_provenance_survives_state_mutation(self):
        """Mutating a state's provenance must not pollute the template."""
        state = make_initial_state(invoice_id="INV-1", raw_text="test")
        state["provenance"]["source"] = "manual"
        assert DEFAULT_STATE_TEMPLATE["provenance"] == {}

    def test_template_unchanged_after_many_states(self):
        """Create many states, mutate them all, template stays pristine."""
        import copy
        snapshot = copy.deepcopy(DEFAULT_STATE_TEMPLATE)
        for i in range(10):
            s = make_initial_state(invoice_id=f"INV-{i}", raw_text=f"text-{i}")
            s["audit_log"].extend(["a", "b", "c"])
            s["route_records"].append({"i": i})
            s["extraction"]["x"] = i
            s["provenance"]["y"] = i
        assert DEFAULT_STATE_TEMPLATE == snapshot
