"""
tests/test_triage.py
Unit tests for eval_triage: compute_invariant_signals and generate_action_plan.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_triage import compute_invariant_signals, generate_action_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extraction(
    vendor="Acme Supplies",
    vendor_ev="Vendor: Acme Supplies",
    amount=100.0,
    amount_ev="Total: $100.00",
    has_po=True,
    po_ev="PO: PO-5544",
) -> dict:
    return {
        "vendor": {"value": vendor, "evidence": vendor_ev},
        "amount": {"value": amount, "evidence": amount_ev},
        "has_po": {"value": has_po, "evidence": po_ev},
    }


def _amount_event(candidates: list, winning_keyword: str | None = None) -> dict:
    evt = {"event": "amount_candidates", "candidates": candidates}
    if winning_keyword is not None:
        evt["winning_keyword"] = winning_keyword
    return evt


# ===========================================================================
# TestComputeInvariantSignals
# ===========================================================================

class TestComputeInvariantSignals:

    # ---- (a) amount_not_in_total_line ------------------------------------

    def test_amount_not_in_total_line(self):
        """Multiple candidates + no winning keyword → flag."""
        evt = _amount_event(
            candidates=[{"value": 100.0}, {"value": 200.0}],
        )
        signals = compute_invariant_signals("", _extraction(), evt)
        assert "amount_not_in_total_line" in signals

    def test_amount_not_flagged_when_keyword_present(self):
        """Multiple candidates BUT winning_keyword present → no flag."""
        evt = _amount_event(
            candidates=[{"value": 100.0}, {"value": 200.0}],
            winning_keyword="total",
        )
        signals = compute_invariant_signals("", _extraction(), evt)
        assert "amount_not_in_total_line" not in signals

    def test_amount_not_flagged_single_candidate(self):
        """Single candidate → no flag regardless of keyword."""
        evt = _amount_event(candidates=[{"value": 100.0}])
        signals = compute_invariant_signals("", _extraction(), evt)
        assert "amount_not_in_total_line" not in signals

    def test_amount_not_flagged_no_event(self):
        """No amount_candidates event at all → no flag."""
        signals = compute_invariant_signals("", _extraction(), None)
        assert "amount_not_in_total_line" not in signals

    # ---- (b) amount_in_non_money_context ---------------------------------

    def test_amount_in_non_money_context_phone(self):
        """Evidence containing a phone number pattern → flag."""
        ext = _extraction(amount_ev="Call 555-123-4567 for details")
        signals = compute_invariant_signals("", ext, None)
        assert "amount_in_non_money_context" in signals

    def test_amount_in_non_money_context_zip(self):
        """Evidence containing a zip code → flag."""
        ext = _extraction(amount_ev="Ship to 90210")
        signals = compute_invariant_signals("", ext, None)
        assert "amount_in_non_money_context" in signals

    def test_amount_in_non_money_context_invoice_id(self):
        """Evidence containing an invoice ID pattern → flag."""
        ext = _extraction(amount_ev="Reference INV-12345")
        signals = compute_invariant_signals("", ext, None)
        assert "amount_in_non_money_context" in signals

    def test_amount_not_flagged_normal_money(self):
        """Normal money evidence → no flag."""
        ext = _extraction(amount_ev="Total: $250.00")
        signals = compute_invariant_signals("", ext, None)
        assert "amount_in_non_money_context" not in signals

    # ---- (c) vendor_is_buyer_entity --------------------------------------

    def test_vendor_is_buyer_entity_direct_match(self):
        """Vendor value matches known buyer name → flag."""
        ext = _extraction(vendor="NorthRiver Corp", vendor_ev="NorthRiver Corp")
        signals = compute_invariant_signals("", ext, None)
        assert "vendor_is_buyer_entity" in signals

    def test_vendor_is_buyer_entity_acme(self):
        """Vendor value is 'Acme Corp' (known buyer) → flag."""
        ext = _extraction(vendor="Acme Corp", vendor_ev="Acme Corp")
        signals = compute_invariant_signals("", ext, None)
        assert "vendor_is_buyer_entity" in signals

    def test_vendor_in_bill_to_block(self):
        """Vendor evidence only in 'Bill To' block → flag."""
        raw = (
            "Invoice #001\n"
            "From: Real Vendor Co\n"
            "Bill To: Some Company\n"
            "  Suspicious Vendor LLC\n"
            "  123 Main St\n"
            "Amount: $500.00\n"
        )
        ext = _extraction(
            vendor="Suspicious Vendor LLC",
            vendor_ev="Suspicious Vendor LLC",
        )
        signals = compute_invariant_signals(raw, ext, None)
        assert "vendor_is_buyer_entity" in signals

    def test_vendor_not_flagged_normal(self):
        """Normal vendor name → no flag."""
        ext = _extraction(vendor="Real Vendor Co", vendor_ev="Vendor: Real Vendor Co")
        signals = compute_invariant_signals(
            "Vendor: Real Vendor Co\nTotal: $100.00", ext, None
        )
        assert "vendor_is_buyer_entity" not in signals

    def test_vendor_not_flagged_email_style(self):
        """Vendor in 'From:' line (email style) → no flag."""
        raw = (
            "From: EmailVendor Inc\n"
            "To: Our Company\n"
            "Amount: $100.00\n"
        )
        ext = _extraction(
            vendor="EmailVendor Inc",
            vendor_ev="EmailVendor Inc",
        )
        signals = compute_invariant_signals(raw, ext, None)
        assert "vendor_is_buyer_entity" not in signals

    # ---- (d) po_missing_digits -------------------------------------------

    def test_po_missing_digits(self):
        """has_po=True but evidence has no digit → flag."""
        ext = _extraction(has_po=True, po_ev="PO-")
        signals = compute_invariant_signals("", ext, None)
        assert "po_missing_digits" in signals

    def test_po_missing_digits_bare_text(self):
        """has_po=True but evidence is just text → flag."""
        ext = _extraction(has_po=True, po_ev="Purchase Order reference")
        signals = compute_invariant_signals("", ext, None)
        assert "po_missing_digits" in signals

    def test_po_not_flagged_with_digits(self):
        """has_po=True and evidence has digits → no flag."""
        ext = _extraction(has_po=True, po_ev="PO-12345")
        signals = compute_invariant_signals("", ext, None)
        assert "po_missing_digits" not in signals

    def test_po_not_flagged_when_false(self):
        """has_po=False → rule not triggered."""
        ext = _extraction(has_po=False, po_ev="No PO on file")
        signals = compute_invariant_signals("", ext, None)
        assert "po_missing_digits" not in signals

    # ---- Edge cases ------------------------------------------------------

    def test_empty_extraction_safe(self):
        """Empty extraction → no crash, empty signals."""
        signals = compute_invariant_signals("some text", {}, None)
        assert signals == []

    def test_none_extraction_safe(self):
        """None-like empty extraction → no crash."""
        signals = compute_invariant_signals("", {}, None)
        assert signals == []

    def test_multiple_signals(self):
        """Input that triggers multiple signals at once."""
        evt = _amount_event(
            candidates=[{"value": 100.0}, {"value": 200.0}],
        )
        ext = _extraction(
            vendor="NorthRiver",
            vendor_ev="NorthRiver",
            has_po=True,
            po_ev="PO-",
        )
        signals = compute_invariant_signals("", ext, evt)
        assert "amount_not_in_total_line" in signals
        assert "vendor_is_buyer_entity" in signals
        assert "po_missing_digits" in signals
        assert len(signals) >= 3


# ===========================================================================
# TestGenerateActionPlan
# ===========================================================================

class TestGenerateActionPlan:

    def test_po_missing_digits_maps_to_verifier(self):
        plan = generate_action_plan("pass", [], ["po_missing_digits"])
        assert plan["owner"] == "verifier"
        assert any("src/verifier.py" in f for f in plan["likely_files"])

    def test_amount_not_in_total_maps_to_llm(self):
        plan = generate_action_plan("pass", [], ["amount_not_in_total_line"])
        assert plan["owner"] == "llm_node"
        assert any("nodes.py" in f for f in plan["likely_files"])

    def test_amount_in_non_money_maps_to_dataset(self):
        plan = generate_action_plan("pass", [], ["amount_in_non_money_context"])
        assert plan["owner"] == "dataset"

    def test_vendor_is_buyer_maps_to_llm(self):
        plan = generate_action_plan("pass", [], ["vendor_is_buyer_entity"])
        assert plan["owner"] == "llm_node"

    def test_terminal_mismatch_maps_to_routing(self):
        plan = generate_action_plan("terminal_mismatch", ["STATUS_MISMATCH"], [])
        assert plan["owner"] == "routing"

    def test_field_mismatch_amount_maps_to_llm(self):
        plan = generate_action_plan("field_mismatch", ["AMOUNT_MISMATCH"], [])
        assert plan["owner"] == "llm_node"

    def test_field_mismatch_vendor_evidence_maps_to_llm(self):
        plan = generate_action_plan("field_mismatch", ["VENDOR_EVIDENCE_MISMATCH"], [])
        assert plan["owner"] == "llm_node"

    def test_default_fallback_is_unknown(self):
        plan = generate_action_plan("field_mismatch", ["SOME_OTHER_CODE"], [])
        assert plan["owner"] == "unknown"

    def test_action_plan_structure(self):
        """All plans have the required keys."""
        plan = generate_action_plan("pass", [], ["po_missing_digits"])
        assert "owner" in plan
        assert "recommended_next_steps" in plan
        assert "likely_files" in plan
        assert isinstance(plan["recommended_next_steps"], list)
        assert isinstance(plan["likely_files"], list)

    def test_bucket_priority_over_signal(self):
        """Bucket-based rules (fatal) take priority over signal rules (warnings)."""
        plan = generate_action_plan(
            "terminal_mismatch", ["STATUS_MISMATCH"], ["po_missing_digits"]
        )
        # terminal_mismatch (bucket) wins over po_missing_digits (signal)
        assert plan["owner"] == "routing"

    def test_llm_root_cause_attached(self):
        """If llm_root_cause provided, it's included in output."""
        plan = generate_action_plan(
            "pass", [], ["po_missing_digits"],
            llm_root_cause="PO regex too loose",
        )
        assert plan.get("llm_root_cause") == "PO regex too loose"

    def test_llm_root_cause_absent_when_none(self):
        """If llm_root_cause is None, key is absent."""
        plan = generate_action_plan("pass", [], [])
        assert "llm_root_cause" not in plan
