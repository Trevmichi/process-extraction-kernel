# AI-Driven Process Mining & Extraction Kernel — Accounts Payable

An end-to-end, local-first process mining engine that reads Accounts Payable policy documents and automatically extracts, graphs, validates, and audits the underlying business process — entirely on your own hardware, with no cloud API calls.

The system ingests raw SOP text, classifies every sentence into a canonical intent ontology using a local LLM, assembles a typed process graph, renders it as a Mermaid.js flowchart, and produces a Gap Analysis report that compares sub-documents against the Master Manual.

---

## Hardware Target

| Component | Spec |
|-----------|------|
| GPU | NVIDIA RTX 5070 (or equivalent ≥ 12 GB VRAM) |
| RAM | 64 GB |
| LLM | Gemma 3:12b via [Ollama](https://ollama.com) |

The LLM path routes to a local Ollama server on `localhost:11434`. The regex heuristic fallback runs on CPU with no GPU required.

---

## Core Capabilities

### Automated NLP Process Extraction
Each source document is sent to a local **Gemma 3:12b** model via the OpenAI-compatible Ollama API. The LLM classifies every sentence against a strict canonical ontology of 14 action types and 6 decision types (`RECEIVE_MESSAGE`, `VALIDATE_FIELDS`, `MATCH_3_WAY`, `APPROVE_OR_REJECT`, etc.) and returns structured JSON intents. The extracted intents are assembled into a typed `ProcessDoc` graph of `Node` and `Edge` objects with full deduplication, sequential wiring, and gateway branching.

### Intelligent Self-Healing & VRAM Management
If the LLM returns zero intents for a chunk, the engine:
1. Waits 10 seconds and retries at temperature 0.0.
2. If still empty — **recursively splits the chunk in half** and processes each sub-chunk independently (Self-Healing).
3. Calls `ollama stop` before each recursive call to free zombie KV-cache VRAM.
4. Tracks the maximum recursion depth per chunk for heatmap analytics.

A 15-second VRAM cool-down and `gc.collect()` pause runs between benchmark tiers to protect the RTX 5070's thermal envelope.

### Gap Analysis — Shadow Process Audit
After all documents are processed, the gap analyzer (`src/gap_analyzer.py`) compares every sub-document against the **Master Manual**:

- **Missing Steps** — intents present in a sub-document but absent from the Master Manual.
- **Missing Logic Paths** — directed edges `(A → B, condition)` in a sub-document but absent from the Master Manual.

Results are written to `outputs/gap_analysis_report.md`.

On the **next run**, the Master Manual extraction reads this report and injects it into the LLM system prompt as a `CRITICAL REQUIREMENTS` block — a self-reinforcing feedback loop that iteratively closes coverage gaps without manual intervention.

### Mermaid.js Flowchart Generation
Each `ProcessDoc` is serialized to a Mermaid `flowchart LR` diagram (`src/mermaid.py`) with:
- **Node shapes:** circle = Start, diamond = Gateway, rectangle = Task, rounded box = End
- **Color coding:** green Start, blue Task, orange Gateway, red End
- Edge labels containing `:` auto-quoted for Mermaid parser compatibility
- Open unknowns attached as a note on the Start node

### Schema Discovery & Ontology Evolution
Every non-canonical intent the LLM emits is caught by `Action.__post_init__` / `Decision.__post_init__`, logged to `data/analytics/schema_suggestions.json` with a frequency counter, and coerced to a safe sentinel. After each run, `outputs/schema_suggestions.md` lists the top unknown types with recommended alias mappings — making ontology gaps immediately actionable.

---

## Getting Started

### 1. Create the virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
```

### 2. Start Ollama with Gemma 3:12b

```bash
ollama pull gemma3:12b
ollama serve
```

Verify the model is available before running:

```bash
ollama list
```

### 3. Run the production pipeline

```powershell
$env:USE_LLM_CLASSIFIER="true"; py -m src.main
```

On subsequent runs the Gap Report from the previous run is automatically fed back into the LLM prompt to close missing coverage.

---

## Outputs

All generated artifacts are written to `outputs/`. Files matching `*.json`, `*.mmd`, and `*.png` are wiped at the start of each `main()` invocation for a clean extraction. Markdown reports and `.jsonl` traces are preserved between runs.

| File | Description |
|------|-------------|
| `ap_master_manual_auto.mmd` | **Primary output.** Renderable Mermaid flowchart of the full AP process extracted from the Master Manual. Open in VS Code with the *yzane.mermaid-editor* extension. |
| `gap_analysis_report.md` | **Shadow process audit.** Lists every step and logic path found in sub-documents but missing from the Master Manual, organized by document. |
| `schema_suggestions.md` | **Ontology discovery report.** Lists non-canonical action/decision types emitted by the LLM, sorted by frequency, with recommended alias mappings for `ACTION_ALIASES` / `DECISION_ALIASES`. |
| `ap_master_manual_auto.json` | Master Manual process graph in machine-readable JSON. |
| `ap_<doc_id>_auto.mmd` | Per-document Mermaid flowcharts. |
| `performance_curve.png` | SP (Success Probability) vs chunk size from the benchmarker. |
| `logic_density_profile.png` | Nodes-per-chunk line graph for the 1.25k gold-standard run. |
| `process_complexity_heatmap.png` | Self-healing depth heatmap — red zones indicate dense/hard-to-parse sections. |

---

## Visualization

Install the **yzane.mermaid-editor** extension in VS Code to preview `.mmd` files directly in the editor. Open `outputs/ap_master_manual_auto.mmd` and use the split-preview panel.

### Color Legend

| Color | Shape | Meaning |
|-------|-------|---------|
| Green (`#9f9`) | Circle `(( ))` | **Start** event |
| Blue (`#bbf`) | Rectangle `[ ]` | **Action / Task** node |
| Orange (`#fdb`) | Diamond `{ }` | **Decision / Gateway** node |
| Red (`#f99`) | Rounded box `( )` | **End** event |

---

## Running the Benchmarker

The benchmarker (`src/benchmarker.py`) runs the full extraction pipeline against `data/ap_heavy_stress.txt` and produces the analytics charts above.

```bash
py -m src.benchmarker
```

Current configuration: `TEST_CHUNKS = [1250]` (Gold Standard baseline). The run produces:
- `outputs/performance_curve.png`
- `outputs/logic_density_profile.png`
- `outputs/process_complexity_heatmap.png`
- `outputs/schema_suggestions.md`
- A terminal summary of the top unknown schema types for immediate ontology action.

Results are persisted to `data/analytics/metrics.db` (`hyperparameter_results` table) and are skipped on re-run if a result already exists for that chunk size.

---

## Knowledge Base

Persistent analytics data lives in `data/analytics/` and is **never wiped** by pipeline runs.

| File | Description |
|------|-------------|
| `data/analytics/metrics.db` | SQLite database — `extraction_logs` and `hyperparameter_results` tables |
| `data/analytics/schema_suggestions.json` | Live frequency counter of non-canonical LLM intent types |

---

## Project Structure

```
process-extraction-kernel/
├── data/
│   ├── analytics/              # Persistent knowledge base (never wiped)
│   │   ├── metrics.db               # SQLite metrics store
│   │   └── schema_suggestions.json  # Live ontology miss counter
│   └── examples/               # Source policy documents (.txt)
├── outputs/                    # Generated artifacts (*.json/*.mmd/*.png wiped each run)
│   └── traces/                 # Execution trace logs (.jsonl, preserved)
├── src/
│   ├── main.py                 # Orchestration entry point
│   ├── llm_classifier.py       # LLM seam — Ollama/OpenAI-compatible, self-healing
│   ├── heuristic.py            # Regex classifier + graph builder (CPU fallback)
│   ├── ontology.py             # Canonical intent ontology + validation sets
│   ├── models.py               # Typed dataclasses (ProcessDoc, Node, Edge, Action…)
│   ├── mermaid.py              # ProcessDoc → Mermaid serializer
│   ├── gap_analyzer.py         # Sub-doc vs. Master Manual gap analysis
│   ├── benchmarker.py          # Grid-search benchmark suite + analytics charts
│   ├── visualizer.py           # Performance curve, heatmap, density profile, schema report
│   ├── database.py             # SQLite metrics store
│   ├── calibrator.py           # Chunk splitting + single-run extraction helper
│   ├── extract.py              # Manually-authored process extractors
│   ├── render.py               # JSON serializer
│   └── diff_tool.py            # Manual vs. auto graph differ
└── tests/
    └── test_validate.py
```
