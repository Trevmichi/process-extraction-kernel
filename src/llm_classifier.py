"""
llm_classifier.py
LLM-backed sentence classifier seam.

Routes to a local Ollama server via the OpenAI-compatible SDK.
Set USE_LLM_CLASSIFIER=true in heuristic.py's caller to route through this.
"""
from __future__ import annotations
import time
from datetime import datetime
from typing import List

from .ontology import VALID_ACTIONS, VALID_DECISIONS, VALID_ACTORS, VALID_ARTIFACTS

# ---------------------------------------------------------------------------
# Self-healing heatmap log
# ---------------------------------------------------------------------------
# Populated by classify_text_block_llm whenever self-healing recursion fires.
# Callers (e.g. benchmarker) should call clear_heatmap_log() before each
# document chunk and get_heatmap_log() after to retrieve depth events.
_heatmap_log: List[dict] = []


def get_heatmap_log() -> List[dict]:
    """Return a snapshot of heatmap events accumulated since last clear."""
    return list(_heatmap_log)


def clear_heatmap_log() -> None:
    """Reset the heatmap log (call before processing each new chunk)."""
    _heatmap_log.clear()

# ---------------------------------------------------------------------------
# Hard-coded GPU / model configuration
# ---------------------------------------------------------------------------
_MODEL = "gemma3:12b"
_NUM_GPU = 1
_TEMPERATURE = 0.1

# 10-minute runway — node recovery over latency; 15k chunks need the headroom.
_CONNECTION_TIMEOUT = 600.0

# Context-window safety headroom
# 32k tokens comfortably covers 15k-word benchmark chunks + system prompt +
# JSON output space.  num_batch=128 prevents VRAM spikes on 12-16 GB cards.
_NUM_CTX = 32768
_NUM_BATCH = 128

# Sliding-window chunking parameters (word count approximates token count)
_CHUNK_TOKENS = 5000
_OVERLAP_TOKENS = 500

# Retry policy — on failure: wait this many seconds then try exactly once more
_RETRY_WAIT_SEC = 30


# ---------------------------------------------------------------------------
# VRAM helpers
# ---------------------------------------------------------------------------

def _ollama_stop() -> None:
    """
    Call `ollama stop <model>` to evict the model from VRAM.

    Used before recursive self-healing sub-chunk calls so the RTX 5070 does
    not accumulate 'zombie' KV-cache context across multiple failed attempts.
    Non-fatal — a warning is printed if the command is unavailable.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["ollama", "stop", _MODEL],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            print(f"[VRAM] ollama stop '{_MODEL}' — VRAM freed.")
        else:
            print(
                f"[VRAM] ollama stop returned code {r.returncode}: "
                f"{r.stderr.strip() or '(no stderr)'}"
            )
    except Exception as exc:
        print(f"[VRAM] ollama stop failed (non-fatal): {exc}")


def _chunk_text(text: str) -> List[str]:
    """
    Split *text* into sequential, overlapping word-based chunks.

    Chunk size : _CHUNK_TOKENS  words
    Overlap    : _OVERLAP_TOKENS words (tail of chunk N is head of chunk N+1)

    Chunks are ALWAYS processed sequentially — never in parallel — to prevent
    simultaneous GPU calls.
    """
    words = text.split()
    if not words:
        return [text]
    step = _CHUNK_TOKENS - _OVERLAP_TOKENS
    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = start + _CHUNK_TOKENS
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step
    return chunks or [text]


def build_system_prompt(gap_report: str = "") -> str:
    gap_section = ""
    if gap_report and gap_report.strip():
        gap_section = f"""
CRITICAL REQUIREMENTS:
The following nodes and logic paths have been identified as missing in previous extractions.
You MUST ensure these are represented if they are supported by the source text.
Do NOT simplify away 'APPROVE', 'REVIEW', or 'UPDATE_STATUS' — preserve them whenever evidence exists.

--- GAP REPORT START ---
{gap_report.strip()}
--- GAP REPORT END ---
"""
    # Expose only canonical values — strip internal sentinels and legacy aliases
    # so the LLM never learns to emit them.
    _allowed_actions   = sorted(a for a in VALID_ACTIONS
                                if a not in {"UNKNOWN_ACTION", "ENTER_DATA"})
    _allowed_decisions = sorted(d for d in VALID_DECISIONS
                                if d != "UNKNOWN_DECISION")

    return f"""You are a JSON-only extraction engine. Output ONLY a raw JSON object. Do not include conversational text, introductions, explanations, or apologies. If no intents are found, return {{"intents": []}}.

Your job: read the text block and extract a chronological JSON array of ALL core Accounts Payable business logic intents found within it.

STRICT ONTOLOGY:
- Allowed Actions: {_allowed_actions}
- Allowed Decisions (Gateways): {_allowed_decisions}
- Allowed Actors: {list(VALID_ACTORS)}
- Allowed Artifacts: {list(VALID_ARTIFACTS)}

CRITICAL: You MUST choose action intents ONLY from the Allowed Actions list above. Do NOT use "UNKNOWN_ACTION" or any value not in that list. If you cannot find an exact match, choose the closest semantic equivalent from the list.

RULES:
1. If the sentence describes a task, return kind: "action" and an intent from Allowed Actions.
2. If the sentence introduces a conditional split or rule, return kind: "decision" and an intent from Allowed Decisions.
3. Use semantic reasoning to map synonyms (e.g., "checks" -> VALIDATE_FIELDS).
4. REQUEST_CLARIFICATION vs NOTIFY: If an actor is reaching out to fix a missing field or get information, use REQUEST_CLARIFICATION. Only use NOTIFY for one-way informational alerts (e.g., "notifies the vendor of rejection").
5. ATOMICITY: Never skip intermediate tasks. Every step mentioned must be a node. If a condition follows a task, the task node must exist and the condition node must follow it. Do not jump straight from a start/previous node to a conditional result if an intermediate action was described.
6. Output ONLY a valid JSON object with a single key 'intents' containing the array. Schema: {{ "intents": [ {{ "kind": "...", "intent": "...", "actor_id": "...", "artifact_id": "...", "branch_label": "...", "parent_id": "...", "evidence_span": "..." }} ] }}
7. PARENT TRACKING: For every intent, if it is the direct result of a previous decision, the `branch_label` must be present. If it is a standard sequential step, leave `branch_label` null.
8. Take your time to be exhaustive. Do not skip any minor sub-steps. Accuracy is more important than brevity.
{gap_section}"""


def _call_llm_single_chunk(
    chunk: str, gap_report: str, client, temperature: float = _TEMPERATURE
) -> List[dict]:
    """
    Send one chunk to the Ollama LLM and return the parsed intents list.
    Raises on network/parse errors — caller handles retry or abort.
    """
    import json

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": build_system_prompt(gap_report=gap_report)},
            {"role": "user", "content": chunk},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        # Hard-coded GPU assignment + safety-headroom context window
        extra_body={"options": {
            "num_ctx":     _NUM_CTX,    # 32 768 — covers 15k-word chunks + overhead
            "num_batch":   _NUM_BATCH,  # 128 — limits VRAM spikes on 12-16 GB cards
            "num_gpu":     _NUM_GPU,
            "num_predict": -1,          # no output-token cap — emit full JSON
            "top_p":       0.9,
            "top_k":       40,
        }},
    )

    raw_json = response.choices[0].message.content
    parsed = json.loads(raw_json)
    return parsed.get("intents", [])


def classify_text_block_llm(
    text: str, gap_report: str = "", _depth: int = 0
) -> List[dict]:
    """
    Classify *text* using the local Ollama LLM with a sliding-window strategy.

    The text is split into overlapping chunks of _CHUNK_TOKENS words with
    _OVERLAP_TOKENS words of overlap.  Each chunk is sent to the LLM
    SEQUENTIALLY (one at a time) to avoid simultaneous GPU calls.

    On failure each chunk gets one retry after a _RETRY_WAIT_SEC pause.
    The client is used as a context manager so the underlying httpx connection
    pool is explicitly closed when the call completes, terminating any
    lingering Ollama connections.

    Returns the combined list of intent dicts from all chunks.
    """
    from openai import OpenAI

    print(
        f"[VRAM CONFIG] num_ctx={_NUM_CTX}, num_batch={_NUM_BATCH} "
        f"(Safety Headroom Active)"
    )

    chunks = _chunk_text(text)
    total_chunks = len(chunks)
    all_intents: List[dict] = []

    # Context-manager ensures the underlying httpx session is closed on exit,
    # terminating any hanging Ollama connections (cleanup requirement).
    with OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        timeout=_CONNECTION_TIMEOUT,
        max_retries=0,  # retries are handled manually below
    ) as client:

        for idx, chunk in enumerate(chunks, start=1):
            ts = datetime.now().strftime("%H:%M:%S")
            print(
                f"[GPU HEARTBEAT: ACTIVE] [{ts}] Chunk {idx}/{total_chunks} — "
                f"{len(chunk.split())} words → {_MODEL}"
            )

            try:
                # SEQUENTIAL: each call completes before the next begins
                chunk_intents = _call_llm_single_chunk(chunk, gap_report, client)

                # Zero-intent guard — empty list is a silent LLM fail, not an exception
                if len(chunk_intents) == 0:
                    print(
                        f"[ZERO-INTENT] Chunk {idx}/{total_chunks} returned 0 intents. "
                        f"Waiting 10s then retrying at temperature=0.0 ..."
                    )
                    time.sleep(10)
                    chunk_intents = _call_llm_single_chunk(
                        chunk, gap_report, client, temperature=0.0
                    )
                    print(
                        f"[ZERO-INTENT RETRY] Chunk {idx}/{total_chunks}: "
                        f"{len(chunk_intents)} intent(s) returned."
                    )

                    # Self-healing: temp=0.0 retry also returned nothing — split in half
                    if len(chunk_intents) == 0:
                        chunk_words = chunk.split()
                        mid = len(chunk_words) // 2
                        half_a = " ".join(chunk_words[:mid])
                        half_b = " ".join(chunk_words[mid:])
                        next_depth = _depth + 1
                        print(
                            f"[SELF-HEALING] 5k chunk failed. "
                            f"Splitting into 2x 2.5k sub-chunks..."
                        )
                        # Record depth event for heatmap — text is the failing chunk
                        print(
                            f"[HEATMAP DATA] Section starting with "
                            f"'{chunk[:30]}...' reached Depth {next_depth}."
                        )
                        _heatmap_log.append({
                            "text_preview": chunk[:30],
                            "depth":        next_depth,
                        })
                        # Free zombie VRAM before recursive calls reload the model
                        _ollama_stop()
                        chunk_intents = []
                        for sub_label, sub_text in (("A", half_a), ("B", half_b)):
                            sub_words = len(sub_text.split())
                            print(
                                f"[SELF-HEALING] Sub-chunk {sub_label} "
                                f"({sub_words} words) ..."
                            )
                            try:
                                sub_intents = classify_text_block_llm(
                                    sub_text, gap_report, _depth=next_depth
                                )
                                chunk_intents.extend(sub_intents)
                            except Exception as sub_err:
                                print(
                                    f"[SELF-HEALING] Sub-chunk {sub_label} failed "
                                    f"(skipping): {sub_err}"
                                )

                all_intents.extend(chunk_intents)

            except Exception as first_err:
                print(
                    f"[LOCAL SEAM ERROR] Chunk {idx}/{total_chunks}: {first_err}\n"
                    f"[RETRY] Waiting {_RETRY_WAIT_SEC}s before retry ..."
                )
                time.sleep(_RETRY_WAIT_SEC)

                try:
                    chunk_intents = _call_llm_single_chunk(chunk, gap_report, client)
                    all_intents.extend(chunk_intents)
                    print(f"[RETRY OK] Chunk {idx}/{total_chunks} recovered.")

                except Exception as second_err:
                    print(f"[RETRY FAILED] Chunk {idx}/{total_chunks}: {second_err}")
                    return []

    # Validate combined LLM output quality.
    # PERMANENT THRESHOLD — do not raise this value.
    # Dry sections of the AP manual legitimately yield 1-4 intents per chunk.
    # The only hard brake is a completely empty combined result (< 1 == 0).
    raw_response = all_intents
    if len(all_intents) < 1:
        try:
            from pathlib import Path as _Path
            _Path("outputs").mkdir(exist_ok=True)
            with open("outputs/last_failed_response.txt", "w", encoding="utf-8") as f:
                f.write(str(raw_response))
        except Exception as _log_err:
            print(f"[LOGGING] Could not write last_failed_response.txt: {_log_err}")
        raise ValueError(
            f"LLM returned zero intents across all {total_chunks} chunk(s) — "
            f"total output was empty. "
            f"Raw response saved to outputs/last_failed_response.txt"
        )

    return all_intents
