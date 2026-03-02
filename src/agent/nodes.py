"""
nodes.py
Generic node executor and LangGraph node factory for the AP process agent.

Each process node in the compiled graph is backed by a handler produced by
`create_node_handler`.  The handler receives the full APState, delegates to
`execute_node` for the actual simulation work, and returns a partial state
dict that LangGraph merges into the shared state.

Smart nodes (ENTER_RECORD, VALIDATE_FIELDS) call the local Ollama LLM to
perform data extraction / validation on raw invoice text.  All other nodes
use fast deterministic logic.
"""
from __future__ import annotations

import json
from typing import Callable

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from .state import APState


# ---------------------------------------------------------------------------
# Module-level LLM instance (shared; avoids repeated construction overhead)
# ---------------------------------------------------------------------------
_llm = ChatOllama(model="gemma3:12b", temperature=0.0, format="json")


# ---------------------------------------------------------------------------
# Intent → human-readable label
# ---------------------------------------------------------------------------
def _intent_label(node_data: dict) -> str:
    """Extract the most descriptive label from a node dict."""
    action   = node_data.get("action") or {}
    decision = node_data.get("decision") or {}
    return (
        action.get("type")
        or decision.get("type")
        or node_data.get("kind", "UNKNOWN")
    )


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
def _call_llm_json(prompt: str) -> dict:
    """
    Invoke the local LLM and return a parsed JSON dict.

    Strips markdown code fences if the model wraps the response in them.
    Returns ``{"_error": <message>}`` on any failure so callers can degrade
    gracefully without raising.
    """
    try:
        response = _llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()

        # Strip ```json ... ``` or ``` ... ``` fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)
    except Exception as exc:
        return {"_error": str(exc)}


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------
def execute_node(state: APState, node_data: dict) -> dict:
    """
    Simulate an agent performing work at *node_data*.

    Smart nodes (ENTER_RECORD, VALIDATE_FIELDS) call the local Ollama LLM.
    All other nodes use deterministic logic.

    Returns a partial state dict suitable for LangGraph's merge.
    """
    node_id = node_data["id"]
    intent  = _intent_label(node_data)
    actor   = (node_data.get("action") or {}).get("actor_id", "")
    actor_tag = f" [{actor}]" if actor else ""

    updates: dict = {"current_node": node_id}

    # ---- Smart node: data extraction ----------------------------------------
    if intent == "ENTER_RECORD":
        prompt = (
            "You are a data extractor. Read the following invoice text and "
            "output a JSON object with exactly three keys: "
            "'vendor' (string), 'amount' (number, no symbols), and "
            "'has_po' (boolean).\n"
            f"Invoice text: {state['raw_invoice_text']}"
        )
        parsed = _call_llm_json(prompt)
        updates["audit_log"] = [f"Extracted data: {parsed}"]
        if "_error" not in parsed:
            updates["vendor"]  = str(parsed.get("vendor",  state["vendor"]))
            updates["amount"]  = float(parsed.get("amount", state["amount"]))
            updates["has_po"]  = bool(parsed.get("has_po",  state["has_po"]))

    # ---- Smart node: field validation ---------------------------------------
    elif intent == "VALIDATE_FIELDS":
        prompt = (
            "You are a validator. Look at this data: "
            f"Vendor: {state['vendor']}, Amount: {state['amount']}, "
            f"PO: {state['has_po']}. "
            'If all fields have valid data (not empty/null), output JSON {"is_valid": true}. '
            'Else output {"is_valid": false}.'
        )
        parsed = _call_llm_json(prompt)
        updates["audit_log"] = [f"Validation result: {parsed}"]
        if "_error" not in parsed:
            updates["status"] = "VALIDATED" if parsed.get("is_valid") else "MISSING_DATA"

    # ---- Standard nodes: deterministic pass-through -------------------------
    else:
        updates["audit_log"] = [f"Executed {intent}{actor_tag} at {node_id}"]
        if intent == "APPROVE":
            updates["status"] = "APPROVED"
        elif intent in ("REJECT", "REJECT_INVOICE"):
            updates["status"] = "REJECTED"
        elif intent == "ESCALATE_TO_DIRECTOR":
            updates["status"] = "ESCALATED"
        elif intent == "MANUAL_REVIEW_NO_PO":
            updates["audit_log"] = [
                f"Executed {intent}{actor_tag} at {node_id}",
                "Flagged for manual review: Missing Purchase Order.",
            ]
            updates["status"] = "EXCEPTION_NO_PO"
        elif intent == "EXECUTE_PAYMENT":
            updates["status"] = "PAID"
        elif intent == "UPDATE_STATUS":
            if state.get("status") not in ("APPROVED", "PAID", "REJECTED"):
                updates["status"] = "CLOSED"
        elif intent == "REQUEST_CLARIFICATION":
            if state.get("status") == "NEW":
                updates["status"] = "PENDING_INFO"

    return updates


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_node_handler(node_id: str, node_data: dict) -> Callable[[APState], dict]:
    """
    Return a LangGraph-compatible callable for *node_id*.

    The returned function is named ``node_<id>`` so it appears legibly
    in LangGraph's debug output and Mermaid diagram exports.
    """
    def handler(state: APState) -> dict:
        return execute_node(state, node_data)

    handler.__name__ = f"node_{node_id}"
    return handler
