"""
tests/test_policy.py
Unit tests for the narrow policy abstraction layer.

Covers: default values, custom overrides, immutability, consumer redirects,
PO mode behavior at both build-time (patch_logic) and runtime (verifier).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

from src.policy import DEFAULT_POLICY, PolicyConfig


# ---------------------------------------------------------------------------
# Default policy reproduces current hardcoded behavior
# ---------------------------------------------------------------------------

class TestDefaultPolicy:

    def test_default_reproduces_current_threshold(self):
        assert DEFAULT_POLICY.approval_threshold == 10_000

    def test_default_condition_strings(self):
        assert DEFAULT_POLICY.approval_condition_above == "amount > 10000"
        assert DEFAULT_POLICY.approval_condition_at_or_below == "amount <= 10000"

    def test_default_po_mode(self):
        assert DEFAULT_POLICY.po_mode == "required"

    def test_default_required_fields(self):
        assert DEFAULT_POLICY.required_fields == ("vendor", "amount", "has_po")

    def test_default_ambiguous_route_intent(self):
        assert DEFAULT_POLICY.ambiguous_route_intent == "task:MANUAL_REVIEW_AMBIGUOUS_ROUTE"

    def test_default_no_route_intent(self):
        assert DEFAULT_POLICY.no_route_intent == "task:MANUAL_REVIEW_NO_ROUTE"

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            DEFAULT_POLICY.approval_threshold = 5000  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Custom policy overrides
# ---------------------------------------------------------------------------

class TestCustomPolicy:

    def test_custom_threshold(self):
        p = PolicyConfig(approval_threshold=5000)
        assert p.approval_condition_above == "amount > 5000"
        assert p.approval_condition_at_or_below == "amount <= 5000"

    def test_custom_required_fields(self):
        p = PolicyConfig(required_fields=("vendor", "amount"))
        assert p.required_fields == ("vendor", "amount")

    def test_custom_po_mode_optional(self):
        p = PolicyConfig(po_mode="optional")
        assert p.po_mode == "optional"

    def test_custom_po_mode_not_applicable(self):
        p = PolicyConfig(po_mode="not_applicable")
        assert p.po_mode == "not_applicable"

    def test_custom_exception_intents(self):
        p = PolicyConfig(
            ambiguous_route_intent="task:CUSTOM_AMBIGUOUS",
            no_route_intent="task:CUSTOM_NO_ROUTE",
        )
        assert p.ambiguous_route_intent == "task:CUSTOM_AMBIGUOUS"
        assert p.no_route_intent == "task:CUSTOM_NO_ROUTE"


# ---------------------------------------------------------------------------
# Consumer redirects — verify downstream modules read from policy
# ---------------------------------------------------------------------------

class TestConsumerRedirects:

    def test_ontology_reads_from_policy(self):
        from src.ontology import (
            APPROVAL_THRESHOLD,
            CONDITION_AMOUNT_ABOVE_THRESHOLD,
            CONDITION_AMOUNT_AT_OR_BELOW_THRESHOLD,
        )
        assert APPROVAL_THRESHOLD == DEFAULT_POLICY.approval_threshold
        assert CONDITION_AMOUNT_ABOVE_THRESHOLD == DEFAULT_POLICY.approval_condition_above
        assert CONDITION_AMOUNT_AT_OR_BELOW_THRESHOLD == DEFAULT_POLICY.approval_condition_at_or_below

    def test_contracts_reads_from_policy(self):
        from src.contracts import _REQUIRED_EXTRACTION_FIELDS
        assert _REQUIRED_EXTRACTION_FIELDS == DEFAULT_POLICY.required_fields

    def test_router_intents_from_policy(self):
        from src.agent.router import _AMBIGUOUS_INTENT, _NO_ROUTE_INTENT
        assert _AMBIGUOUS_INTENT == DEFAULT_POLICY.ambiguous_route_intent
        assert _NO_ROUTE_INTENT == DEFAULT_POLICY.no_route_intent


# ---------------------------------------------------------------------------
# PO mode — verifier behavior
# ---------------------------------------------------------------------------

_RAW = "INVOICE\nVendor: Acme\nTotal: $100.00\nPO: PO-1234"


def _extraction_with_bad_po_evidence():
    return {
        "vendor": {"value": "Acme", "evidence": "Vendor: Acme"},
        "amount": {"value": 100.0, "evidence": "Total: $100.00"},
        "has_po": {"value": True, "evidence": "FABRICATED_EVIDENCE"},
    }


class TestPoModeVerifier:

    def test_po_required_enforces_has_po(self):
        """Default po_mode='required' — bad PO evidence → failure code."""
        from src.verifier import verify_extraction
        valid, codes, _prov = verify_extraction(_RAW, _extraction_with_bad_po_evidence())
        assert not valid
        po_codes = [c for c in codes if "PO" in c or "EVIDENCE" in c]
        assert len(po_codes) > 0

    def test_po_optional_still_verifies_has_po(self):
        """po_mode='optional' — verifier still checks has_po evidence quality."""
        from src.verifier import verify_extraction
        optional_policy = PolicyConfig(po_mode="optional")
        with mock_patch("src.verifier.DEFAULT_POLICY", optional_policy):
            valid, codes, _prov = verify_extraction(_RAW, _extraction_with_bad_po_evidence())
        # Verifier still runs has_po check; bad evidence still fails
        po_codes = [c for c in codes if "PO" in c or "EVIDENCE" in c]
        assert len(po_codes) > 0

    def test_po_not_applicable_skips_has_po_verification(self):
        """po_mode='not_applicable' — verifier skips has_po entirely."""
        from src.verifier import verify_extraction
        na_policy = PolicyConfig(po_mode="not_applicable")
        with mock_patch("src.verifier.DEFAULT_POLICY", na_policy):
            valid, codes, _prov = verify_extraction(_RAW, _extraction_with_bad_po_evidence())
        # No PO-related failure codes — has_po validation was skipped
        po_codes = [c for c in codes if "PO" in c]
        assert len(po_codes) == 0


# ---------------------------------------------------------------------------
# PO mode — build-time (patch_logic)
# ---------------------------------------------------------------------------

class TestPoModePatchLogic:

    def _run_patch(self, po_mode: str) -> dict:
        """Run _patch() with the given po_mode and return the patched graph."""
        from patch_logic import _patch
        policy = PolicyConfig(po_mode=po_mode)
        with mock_patch("patch_logic.DEFAULT_POLICY", policy):
            graph = json.loads(Path("outputs/ap_master_manual_auto.json").read_text())
            patched, _changelog = _patch(graph)
            return patched

    def test_po_required_injects_guard_edge(self):
        """po_mode='required' — n3→n_exception edge IS present."""
        patched = self._run_patch("required")
        guard_edges = [
            e for e in patched["edges"]
            if e.get("frm") == "n3" and e.get("to") == "n_exception"
        ]
        assert len(guard_edges) == 1
        assert "has_po == false" in guard_edges[0]["condition"]

    def test_po_optional_no_guard_edge(self):
        """po_mode='optional' — n3→n_exception edge is NOT present,
        but n3→n_reject (MISSING_DATA) IS still present."""
        patched = self._run_patch("optional")
        guard_edges = [
            e for e in patched["edges"]
            if e.get("frm") == "n3" and e.get("to") == "n_exception"
        ]
        assert len(guard_edges) == 0
        # MISSING_DATA guard still present
        reject_edges = [
            e for e in patched["edges"]
            if e.get("frm") == "n3" and e.get("to") == "n_reject"
        ]
        assert len(reject_edges) == 1
