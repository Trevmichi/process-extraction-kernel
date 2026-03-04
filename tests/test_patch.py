"""
tests/test_patch.py
Unit tests for patch_logic.py.

Tests verify:
- Patched nodes carry origin metadata (patch_id, origin, rationale)
- Patched edges carry origin metadata
- art_account_code artifact is injected when absent
- art_account_code is NOT duplicated when already present
"""
from __future__ import annotations

import json
import copy
from pathlib import Path

import pytest

# Import patch internals directly
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from patch_logic import _patch, NEW_NODES, ART_ACCOUNT_CODE


# ---------------------------------------------------------------------------
# Minimal source graph (mimics ap_master_manual_auto.json structure)
# ---------------------------------------------------------------------------

def _minimal_source() -> dict:
    """
    Minimal graph that has the same topology as the real source so patches
    apply without KeyError.
    """
    return {
        "actors": [
            {"id": "role_ap_clerk",  "type": "human_role", "name": "AP Clerk"},
            {"id": "role_manager",   "type": "human_role", "name": "Manager"},
            {"id": "role_director",  "type": "human_role", "name": "Director"},
            {"id": "sys_erp",        "type": "system",     "name": "ERP"},
        ],
        "artifacts": [
            {"id": "art_invoice",  "type": "document", "name": "Invoice"},
            {"id": "art_po",       "type": "record",   "name": "Purchase Order"},
            {"id": "art_grn",      "type": "record",   "name": "Goods Receipt"},
            {"id": "art_payment",  "type": "record",   "name": "Payment"},
        ],
        "nodes": [
            {
                "id": "n1",  "kind": "event", "name": "Start",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "event:start"},
            },
            {
                "id": "n3",  "kind": "task",  "name": "Validate Fields",
                "action": {
                    "type": "VALIDATE_FIELDS", "actor_id": "role_ap_clerk",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:VALIDATE_FIELDS"},
            },
            {
                "id": "n4",  "kind": "gateway", "name": "3-Way Match",
                "action": None,
                "decision": {"type": "MATCH_3_WAY", "inputs": [], "expression": None},
                "evidence": [],
                "meta": {"canonical_key": "gw:MATCH_3_WAY"},
            },
            {
                "id": "n5",  "kind": "task",  "name": "Approve",
                "action": {
                    "type": "APPROVE", "actor_id": "role_director",
                    "artifact_id": "art_invoice", "extra": {},
                },
                "decision": None, "evidence": [],
                "meta": {"canonical_key": "task:APPROVE"},
            },
            {
                "id": "n32", "kind": "end",   "name": "End",
                "action": None, "decision": None, "evidence": [],
                "meta": {"canonical_key": "end:end"},
            },
        ],
        "edges": [
            {"frm": "n1",  "to": "n3",  "condition": None},
            {"frm": "n3",  "to": "n4",  "condition": None},
            {"frm": "n4",  "to": "n5",  "condition": "MATCH_3_WAY"},
            {"frm": "n5",  "to": "n32", "condition": None},
        ],
    }


# ===========================================================================
# art_account_code injection
# ===========================================================================

class TestArtAccountCodeInjection:

    def test_artifact_injected_when_absent(self):
        """art_account_code is added to artifacts when not present."""
        data = _minimal_source()
        art_ids_before = {a["id"] for a in data["artifacts"]}
        assert ART_ACCOUNT_CODE["id"] not in art_ids_before

        patched, _ = _patch(data)

        art_ids_after = {a["id"] for a in patched["artifacts"]}
        assert ART_ACCOUNT_CODE["id"] in art_ids_after

    def test_artifact_not_duplicated_when_already_present(self):
        """If art_account_code is already present, it must not be added again."""
        data = _minimal_source()
        data["artifacts"].append(copy.deepcopy(ART_ACCOUNT_CODE))

        patched, _ = _patch(data)

        count = sum(
            1 for a in patched["artifacts"]
            if a["id"] == ART_ACCOUNT_CODE["id"]
        )
        assert count == 1, f"Expected 1 occurrence, got {count}"

    def test_artifact_schema_valid(self):
        data = _minimal_source()
        patched, _ = _patch(data)
        art = next(a for a in patched["artifacts"] if a["id"] == ART_ACCOUNT_CODE["id"])
        assert art["id"]   == "art_account_code"
        assert art["name"] == "GL Account Code"
        assert art["type"] in ("record", "field", "document")


# ===========================================================================
# Patched node origin metadata
# ===========================================================================

class TestPatchedNodeMetadata:

    def test_all_patched_nodes_have_origin_patch(self):
        data = _minimal_source()
        patched, _ = _patch(data)

        node_by_id = {n["id"]: n for n in patched["nodes"]}
        for node_spec in NEW_NODES:
            nid  = node_spec["id"]
            assert nid in node_by_id, f"Expected patched node {nid!r} to be present"
            meta = node_by_id[nid].get("meta", {})
            assert meta.get("origin") == "patch", (
                f"Node {nid!r} meta.origin should be 'patch', got {meta.get('origin')!r}"
            )

    def test_all_patched_nodes_have_patch_id(self):
        data = _minimal_source()
        patched, _ = _patch(data)

        node_by_id = {n["id"]: n for n in patched["nodes"]}
        for node_spec in NEW_NODES:
            nid  = node_spec["id"]
            meta = node_by_id[nid].get("meta", {})
            assert "patch_id" in meta, f"Node {nid!r} missing meta.patch_id"
            assert meta["patch_id"], f"Node {nid!r} meta.patch_id is empty"

    def test_all_patched_nodes_have_rationale(self):
        data = _minimal_source()
        patched, _ = _patch(data)

        node_by_id = {n["id"]: n for n in patched["nodes"]}
        for node_spec in NEW_NODES:
            nid  = node_spec["id"]
            meta = node_by_id[nid].get("meta", {})
            assert "rationale" in meta, f"Node {nid!r} missing meta.rationale"
            assert meta["rationale"], f"Node {nid!r} meta.rationale is empty"


# ===========================================================================
# Patched edge origin metadata
# ===========================================================================

class TestPatchedEdgeMetadata:

    def _patched_edges(self, source_data: dict) -> list[dict]:
        """Return only the edges that were added by _patch (have meta.origin=patch)."""
        patched, _ = _patch(source_data)
        return [e for e in patched["edges"] if (e.get("meta") or {}).get("origin") == "patch"]

    def test_new_edges_have_patch_origin(self):
        patched_edges = self._patched_edges(_minimal_source())
        assert len(patched_edges) > 0, "No patched edges found"

    def test_new_edges_have_patch_id(self):
        for edge in self._patched_edges(_minimal_source()):
            meta = edge.get("meta", {})
            assert "patch_id" in meta, f"Edge {edge} missing meta.patch_id"
            assert meta["patch_id"]

    def test_threshold_edges_have_canonical_dsl_conditions(self):
        """Patch 1 edges must use canonical DSL conditions (spaces around op)."""
        data = _minimal_source()
        patched, _ = _patch(data)

        threshold_edges = [
            e for e in patched["edges"]
            if e.get("frm") == "n_threshold"
        ]
        assert len(threshold_edges) == 2
        conditions = {e["condition"] for e in threshold_edges}
        assert "amount > 10000"  in conditions, f"Expected 'amount > 10000', got {conditions}"
        assert "amount <= 10000" in conditions, f"Expected 'amount <= 10000', got {conditions}"

    def test_data_loophole_edges_have_canonical_dsl_conditions(self):
        """Patch 2 edges must use canonical DSL conditions."""
        data = _minimal_source()
        patched, _ = _patch(data)

        n3_edges = [e for e in patched["edges"] if e.get("frm") == "n3"]
        conditions = {e.get("condition") for e in n3_edges}
        assert 'status == "MISSING_DATA"' in conditions
        assert (
            'status != "BAD_EXTRACTION" AND status != "NEEDS_RETRY" '
            'AND status != "MISSING_DATA" AND has_po == false'
            in conditions
        )


# ===========================================================================
# Idempotency
# ===========================================================================

class TestPatchIdempotency:

    def test_patch_is_idempotent_for_art_account_code(self):
        """Running _patch twice must not add art_account_code twice."""
        data = _minimal_source()
        data, _ = _patch(data)
        data, _ = _patch(data)

        count = sum(
            1 for a in data["artifacts"]
            if a["id"] == ART_ACCOUNT_CODE["id"]
        )
        assert count == 1
