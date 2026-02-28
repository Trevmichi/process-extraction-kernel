"""
llm_classifier.py
LLM-backed sentence classifier seam.

Routes to a local Ollama server via the OpenAI-compatible SDK.
Set USE_LLM_CLASSIFIER=true in heuristic.py's caller to route through this.
"""
from __future__ import annotations
from typing import List

from .ontology import VALID_ACTIONS, VALID_DECISIONS, VALID_ACTORS, VALID_ARTIFACTS


def build_system_prompt() -> str:
    return f"""You are a strict Accounts Payable Process Extraction Engine.
Your job is to read a full block of text and extract a chronological JSON array of ALL core business logic intents found within it.

STRICT ONTOLOGY:
- Allowed Actions: {list(VALID_ACTIONS)}
- Allowed Decisions (Gateways): {list(VALID_DECISIONS)}
- Allowed Actors: {list(VALID_ACTORS)}
- Allowed Artifacts: {list(VALID_ARTIFACTS)}

RULES:
1. If the sentence describes a task, return kind: "action" and an intent from Allowed Actions.
2. If the sentence introduces a conditional split or rule, return kind: "decision" and an intent from Allowed Decisions.
3. Use semantic reasoning to map synonyms (e.g., "checks" -> VALIDATE_FIELDS).
4. REQUEST_CLARIFICATION vs NOTIFY: If an actor is reaching out to fix a missing field or get information, use REQUEST_CLARIFICATION. Only use NOTIFY for one-way informational alerts (e.g., "notifies the vendor of rejection").
5. ATOMICITY: Never skip intermediate tasks. Every step mentioned must be a node. If a condition follows a task, the task node must exist and the condition node must follow it. Do not jump straight from a start/previous node to a conditional result if an intermediate action was described.
6. Output ONLY a valid JSON object with a single key 'intents' containing the array. Schema: {{ "intents": [ {{ "kind": "...", "intent": "...", "actor_id": "...", "artifact_id": "...", "branch_label": "...", "parent_id": "...", "evidence_span": "..." }} ] }}
7. PARENT TRACKING: For every intent, if it is the direct result of a previous decision, the `branch_label` must be present. If it is a standard sequential step, leave `branch_label` null.
"""


def classify_text_block_llm(text: str) -> List[dict]:
    import json
    from openai import OpenAI

    # Connects to the local Ollama server running on your machine
    try:
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

        response = client.chat.completions.create(
            model="gemma3:12b",
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )

        # Parse the JSON object and extract the intents array
        raw_json = response.choices[0].message.content
        parsed_data = json.loads(raw_json)
        return parsed_data.get("intents", [])

    except Exception as e:
        print(f"[LOCAL SEAM ERROR] {e}")
        return []
