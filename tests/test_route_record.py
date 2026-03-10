from __future__ import annotations

import json

from src.agent.nodes import execute_node
from src.agent.router import _NO_ROUTE_INTENT, route_edge


def _state(**overrides) -> dict:
    base = {
        "invoice_id": "INV-ROUTE",
        "vendor": "Acme",
        "amount": 500.0,
        "has_po": True,
        "po_match": True,
        "match_3_way": True,
        "match_result": "MATCH",
        "status": "NEW",
        "current_node": "n0",
        "last_gateway": "",
        "audit_log": [],
        "route_records": [],
        "raw_text": "",
        "extraction": {},
        "provenance": {},
        "retry_count": 0,
        "failure_codes": [],
    }
    base.update(overrides)
    return base


def _gateway_node(node_id: str = "n_gw") -> dict:
    return {"id": node_id, "kind": "gateway", "action": None, "decision": {}, "meta": {}}


class TestRouteRecordEmission:

    def test_conditional_match_emits_exact_route_record(self):
        state = _state(has_po=True)
        node = _gateway_node("n_gw_1")
        edges = [
            {"frm": "n_gw_1", "to": "n_fallback", "condition": None},
            {"frm": "n_gw_1", "to": "n_yes", "condition": "has_po == true"},
            {"frm": "n_gw_1", "to": "n_no", "condition": "has_po == false"},
        ]

        updates = execute_node(state, node, edges, station_map={})

        assert route_edge(state, edges, node, station_map={}) == "n_yes"

        assert updates["route_records"] == [
            {
                "gateway_id": "n_gw_1",
                "outgoing_edge_set": [
                    {"to": "n_fallback", "raw_condition": None},
                    {"to": "n_no", "raw_condition": "has_po == false"},
                    {"to": "n_yes", "raw_condition": "has_po == true"},
                ],
                "normalized_conditions": [
                    {"to": "n_fallback", "raw_condition": None, "normalized_condition": None},
                    {
                        "to": "n_no",
                        "raw_condition": "has_po == false",
                        "normalized_condition": "has_po == false",
                    },
                    {
                        "to": "n_yes",
                        "raw_condition": "has_po == true",
                        "normalized_condition": "has_po == true",
                    },
                ],
                "predicate_results": [
                    {
                        "to": "n_no",
                        "normalized_condition": "has_po == false",
                        "matched": False,
                        "phase": "conditional",
                    },
                    {
                        "to": "n_yes",
                        "normalized_condition": "has_po == true",
                        "matched": True,
                        "phase": "conditional",
                    },
                    {
                        "to": "n_fallback",
                        "normalized_condition": None,
                        "matched": None,
                        "phase": "fallback",
                    },
                ],
                "selected_edge": {"to": "n_yes", "condition": "has_po == true"},
                "reason": "condition_match",
                "exception_mapping": None,
                "schema_version": "route_record_v1",
            }
        ]

        parsed = [json.loads(x) for x in updates["audit_log"] if isinstance(x, str) and x.startswith("{")]
        decision = next(e for e in parsed if e.get("event") == "route_decision")
        assert decision["selected"] == "n_yes"
        assert decision["reason"] == "condition_match"

    def test_no_route_emits_exception_mapping(self):
        state = _state(has_po=True, amount=500.0)
        node = _gateway_node("n_gw_2")
        edges = [
            {"frm": "n_gw_2", "to": "n_z", "condition": "amount > 9999"},
            {"frm": "n_gw_2", "to": "n_a", "condition": "has_po == false"},
        ]
        station_map = {_NO_ROUTE_INTENT: "n_exc_no_route"}

        updates = execute_node(state, node, edges, station_map=station_map)

        assert route_edge(state, edges, node, station_map=station_map) == "n_exc_no_route"

        assert updates["route_records"] == [
            {
                "gateway_id": "n_gw_2",
                "outgoing_edge_set": [
                    {"to": "n_a", "raw_condition": "has_po == false"},
                    {"to": "n_z", "raw_condition": "amount > 9999"},
                ],
                "normalized_conditions": [
                    {
                        "to": "n_a",
                        "raw_condition": "has_po == false",
                        "normalized_condition": "has_po == false",
                    },
                    {
                        "to": "n_z",
                        "raw_condition": "amount > 9999",
                        "normalized_condition": "amount > 9999",
                    },
                ],
                "predicate_results": [
                    {
                        "to": "n_a",
                        "normalized_condition": "has_po == false",
                        "matched": False,
                        "phase": "conditional",
                    },
                    {
                        "to": "n_z",
                        "normalized_condition": "amount > 9999",
                        "matched": False,
                        "phase": "conditional",
                    },
                ],
                "selected_edge": None,
                "reason": "no_route",
                "exception_mapping": {
                    "intent_key": "task:MANUAL_REVIEW_NO_ROUTE",
                    "sink_node": "n_exc_no_route",
                },
                "schema_version": "route_record_v1",
            }
        ]

        parsed = [json.loads(x) for x in updates["audit_log"] if isinstance(x, str) and x.startswith("{")]
        decision = next(e for e in parsed if e.get("event") == "route_decision")
        assert decision["selected"] is None
        assert decision["reason"] == "no_route"
