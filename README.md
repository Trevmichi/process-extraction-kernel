# Process Extraction Kernel: Local LLM Edition

A local-first pipeline that reads Accounts Payable policy documents and automatically extracts, graphs, and validates the underlying business process — entirely on your own hardware, with no cloud API calls required.

---

## Hardware Target

| Component | Spec |
|-----------|------|
| GPU | NVIDIA RTX 5070 |
| RAM | 64 GB |
| LLM | Gemma 3:12b via [Ollama](https://ollama.com) |

The regex heuristic path runs on CPU instantly. The LLM path routes to a local Ollama server on `localhost:11434` and is optimized for the above configuration.

---

## Architecture

The engine runs a three-stage pipeline on every invocation.

### Stage A — Heuristic Extraction

Each source document is split into sentences and classified into a canonical intent ontology (`RECEIVE_MESSAGE`, `VALIDATE_FIELDS`, `MATCH_3_WAY`, `APPROVE_OR_REJECT`, etc.).

Two classifiers are available and automatically fall back on each other:

1. **LLM classifier** (`src/llm_classifier.py`) — sends the full text block to a local Gemma 3:12b model via the OpenAI-compatible Ollama API. The system prompt is dynamically augmented with a Gap Report from the previous run, forcing the model to preserve intents it previously dropped.
2. **Regex heuristic** (`src/heuristic.py`) — a deterministic verb-pattern matcher that runs instantly with zero GPU load. Used when `USE_LLM_CLASSIFIER` is unset or when the LLM call fails.

The extracted intents are assembled into a `ProcessDoc` — a typed graph of `Node` and `Edge` objects — by a graph builder that handles sequential wiring, gateway branching, loop-back edges, and deduplication.

### Stage B — Mermaid Graph Generation

Each `ProcessDoc` is serialized to a Mermaid `flowchart LR` diagram (`src/mermaid.py`).

- **Node shapes:** circle = Start, diamond = Gateway/Decision, rectangle = Task, rounded box = End
- **Color coding:** see Legend below
- Styling uses individual `style` statements (maximum IDE compatibility — no `classDef`)
- Edge labels containing `:` are automatically quoted to satisfy the Mermaid parser
- An unknowns note is attached to the start node when open questions remain

### Stage C — Gap Analysis & Auto-Patch

After all documents are processed, the gap analyzer (`src/gap_analyzer.py`) compares every sub-document against the Master Manual:

- **Missing Steps** — intents present in a sub-document but absent from the Master Manual
- **Missing Logic Paths** — directed edges `(A → B, condition)` present in a sub-document but absent from the Master Manual

Results are written to `outputs/gap_analysis_report.md`.

On the **next run**, the Master Manual extraction reads this report and injects it into the LLM system prompt as a `CRITICAL REQUIREMENTS` block. This feedback loop iteratively closes coverage gaps without any manual intervention.

---

## Getting Started

### 1. Create the virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
```

### 2. Start Ollama (for LLM mode)

```bash
ollama pull gemma3:12b
ollama serve
```

### 3. Run the engine

**Regex-only mode** (fast, no GPU required):
```bash
py -m src.main
```

**LLM-guided mode** (requires Ollama running locally):
```powershell
$env:USE_LLM_CLASSIFIER="true"; py -m src.main
```

On subsequent runs the Gap Report from the previous run is automatically fed back into the LLM prompt for the Master Manual extraction.

---

## Visualization

Install the **yzane.mermaid-editor** extension in VS Code to preview `.mmd` files directly in the editor. Open any file in `outputs/` ending in `.mmd` and use the split-preview panel to see the rendered flowchart alongside the source.

---

## Output Files

All artifacts are written to the `outputs/` folder after each run.

| File pattern | Description |
|---|---|
| `ap_<doc_id>.json` | Manually-authored canonical process graph (JSON) |
| `ap_<doc_id>.mmd` | Mermaid diagram for the manually-authored graph |
| `ap_<doc_id>_auto.json` | Auto-extracted process graph (JSON) |
| `ap_<doc_id>_auto.mmd` | Mermaid diagram for the auto-extracted graph |
| `ap_master_manual_auto.json` | Master Manual auto-extract (aggregated source of truth) |
| `ap_master_manual_auto.mmd` | Mermaid diagram for the Master Manual |
| `diff_<doc_id>_manual_vs_auto.md` | Node/edge diff between manual and auto graphs |
| `gap_analysis_report.md` | Gap analysis: sub-docs vs. Master Manual |
| `traces/run_<doc_id>.jsonl` | Execution trace events (JSONL) |

---

## Color Legend

| Color | Shape | Meaning |
|-------|-------|---------|
| Green (`#9f9`) | Circle `(( ))` | **Start** event |
| Blue (`#bbf`) | Rectangle `[ ]` | **Action / Task** node |
| Orange (`#fdb`) | Diamond `{ }` | **Decision / Gateway** node |
| Red (`#f99`) | Rounded box `( )` | **End** event |

---

## Project Structure

```
process-extraction-kernel/
├── data/
│   └── examples/          # Source policy documents (.txt)
├── outputs/               # All generated artifacts
│   └── traces/            # Execution trace logs
├── src/
│   ├── heuristic.py       # Regex-based intent classifier + graph builder
│   ├── llm_classifier.py  # LLM seam (Ollama / OpenAI-compatible)
│   ├── mermaid.py         # ProcessDoc → Mermaid serializer
│   ├── gap_analyzer.py    # Sub-doc vs. Master Manual gap analysis
│   ├── models.py          # Typed dataclasses (ProcessDoc, Node, Edge, …)
│   ├── ontology.py        # Canonical intent ontology + validation sets
│   ├── extract.py         # Manually-authored extractors (doc_001–005)
│   ├── main.py            # Orchestration entry point
│   ├── render.py          # JSON serializer
│   ├── referee.py         # Unknown/gap auto-annotation
│   ├── branch_model.py    # Branch wiring post-processor
│   ├── canonicalize.py    # Manual-to-explicit canonicalization
│   └── diff_tool.py       # Manual vs. auto graph differ
└── tests/
    └── test_validate.py
```
