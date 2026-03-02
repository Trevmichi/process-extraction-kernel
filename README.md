# Enterprise AP Automation: Deterministic Process Extraction & Graph Routing

> **Core Philosophy:** Process Mining must precede Process Automation.
>
> Most AI automation fails because it asks an LLM to simultaneously *understand* a process
> and *execute* it — leading to hallucinations, inconsistent decisions, and zero audit trail.
> This system separates the two concerns completely:
>
> - **The Brain** — A local LLM reads unstructured SOPs and extracts the rules, nodes, and edges.
> - **The Rails** — A compiled LangGraph state machine executes those rules deterministically, forever.
>
> Once mined, the process graph becomes code. The LLM is only ever called for narrow, bounded tasks
> (extract *these three fields* from *this text*). All routing decisions are made by the graph.

---

## What This System Does

This repository is an end-to-end Enterprise AI pipeline for Accounts Payable invoice processing. It ingests raw policy documents, mines the embedded business logic, compiles it into an executable graph, and processes unstructured invoices through that graph using tightly constrained LLM micro-agents.

| Property | Value |
|----------|-------|
| **Routing engine** | 100% deterministic (LangGraph) |
| **LLM hallucination surface** | Two bounded extraction tasks only |
| **Auditability** | Full per-step audit log on every invoice |
| **Deployment** | Fully local — no cloud API calls |
| **LLM** | Gemma 3:12b via Ollama (`localhost:11434`) |

---

## Architecture: The 7-Phase Pipeline

```
  Raw SOP Text
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Phase 1 & 2     │────▶│  Phase 3         │
│  Process Mining  │     │  Micro-Agents    │
│  & Compilation   │     │  (LLM bounded)   │
└──────────────────┘     └──────────────────┘
       │                          │
       ▼                          ▼
┌──────────────────┐     ┌──────────────────┐
│  Phase 5 & 7     │     │  Phase 4         │
│  Dynamic Logic   │     │  Batch Runner    │
│  Patching        │     │  (Queue sim.)    │
└──────────────────┘     └──────────────────┘
       │                          │
       └──────────┬───────────────┘
                  ▼
        ┌──────────────────┐
        │  Phase 6         │
        │  Enterprise UI   │
        │  (Streamlit)     │
        └──────────────────┘
```

### Phase 1 & 2 — Process Mining & Graph Compilation

The pipeline reads Accounts Payable policy documents (`.txt` SOPs) and runs them through a local **Gemma 3:12b** model via the OpenAI-compatible Ollama API.

Each sentence is classified against a strict canonical ontology of **14 action types** and **6 decision types** (`RECEIVE_MESSAGE`, `VALIDATE_FIELDS`, `MATCH_3_WAY`, `APPROVE`, etc.). The extracted intents are assembled into a typed `ProcessDoc` graph of `Node` and `Edge` objects with full deduplication, sequential wiring, and gateway branching.

The resulting graph is serialized to a machine-readable JSON (`outputs/ap_master_manual_auto.json`) and a human-readable Mermaid flowchart (`outputs/ap_master_manual_auto.mmd`).

`build_ap_graph(json_path)` in `src/agent/compiler.py` then reads this JSON and compiles it into an executable **LangGraph `CompiledGraph`** — a finite state machine where every transition is governed by the extracted rules, not by an LLM at runtime.

**Self-Healing Extraction:** If the LLM returns zero intents for a chunk, the engine recursively splits it in half and retries, tracking depth for heatmap analytics. A Gap Analyzer (`src/gap_analyzer.py`) compares sub-documents against the Master Manual and feeds missing coverage back into the next extraction run as a `CRITICAL REQUIREMENTS` prompt block.

### Phase 3 — LLM Micro-Agents (Bounded Data Extraction)

Two nodes in the compiled graph call the LLM. All other nodes are deterministic.

| Node | LLM Task | Output |
|------|----------|--------|
| `ENTER_RECORD` | Extract `vendor`, `amount`, `has_po` from raw invoice text | Updates `APState` |
| `VALIDATE_FIELDS` | Check if extracted fields are non-null and valid | Sets `status = VALIDATED` or `MISSING_DATA` |

The LLM is given an explicit JSON schema and instructed to return *only* that schema. All downstream routing reads the state values; the LLM never makes a routing decision.

### Phase 4 — Batch Processing

`batch_runner.py` simulates a real-world invoice queue. It compiles the graph once, then runs a list of raw-text invoices through it sequentially, printing a formatted results table and aggregate summary at the end.

### Phase 5 & 7 — Dynamic Logic Patching

The Master Manual SOP may have gaps — missing thresholds, missing exception routes. `patch_logic.py` programmatically injects guardrails directly into the JSON graph before compilation, without touching the source document.

**Patches currently applied:**

| Patch | Trigger | Outcome |
|-------|---------|---------|
| Amount Threshold | `amount > $10,000` after 3-way match passes | `ESCALATE_TO_DIRECTOR` |
| Bad Data Rejection | `status == MISSING_DATA` after validation | `REJECT_INVOICE` |
| No-PO Exception | `has_po == False` after validation passes | `MANUAL_REVIEW_NO_PO` |

These patches are re-applied every time `patch_logic.py` is run, making the guardrail layer fully version-controlled and reproducible.

### Phase 6 — Enterprise UI

`app.py` is a Streamlit dashboard that exposes the full agent pipeline to non-technical users.

- **Tabbed input:** paste raw text, upload a `.txt` file, or pick a test example
- **Live status widget:** shows extraction and routing progress in real time (`st.status`)
- **Metric cards:** vendor, amount, PO status, final routing decision
- **Color-coded banners:** green APPROVED, amber ESCALATED/EXCEPTION, red REJECTED
- **Audit trail expander:** every LLM call and graph transition, labelled and icon-tagged
- **Batch Ledger sidebar:** session history with status breakdown and recent-invoice table

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Gemma 3:12b via [Ollama](https://ollama.com) |
| LLM interface | `langchain-ollama` (`ChatOllama`) |
| Graph execution | [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`) |
| State schema | Python `TypedDict` with `Annotated` reducers |
| Web UI | [Streamlit](https://streamlit.io) |
| Analytics | `matplotlib`, `numpy`, SQLite |
| Runtime | Python 3.11+, local-only (no cloud) |

---

## Quickstart

### 1. Environment setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Start Ollama

```bash
ollama pull gemma3:12b
ollama serve
```

Verify the model is available:

```bash
ollama list
# Should show: gemma3:12b
```

### 3. Mine a process document (optional — pre-mined JSON is included)

```powershell
$env:USE_LLM_CLASSIFIER="true"; py -m src.main
```

This reads `data/examples/ap_master_manual.txt`, classifies it with the LLM, and writes `outputs/ap_master_manual_auto.json` and `outputs/ap_master_manual_auto.mmd`.

### 4. Patch the baseline logic

```bash
py patch_logic.py
```

Reads `outputs/ap_master_manual_auto.json`, injects the three guardrail patches, and writes `outputs/ap_master_manual_auto_patched.json`. Run this after every re-extraction.

### 5. Run the batch tester

```bash
py batch_runner.py
```

Processes 4 diverse test invoices through the patched graph and prints a results table.

### 6. Launch the UI

```bash
streamlit run app.py
```

Opens the enterprise dashboard at `http://localhost:8501`.

---

## Benchmark & Analytics

The benchmarker (`src/benchmarker.py`) runs the full extraction pipeline and produces analytics charts.

```bash
py -m src.benchmarker
```

| Output | Description |
|--------|-------------|
| `outputs/performance_curve.png` | Success Probability vs chunk size |
| `outputs/logic_density_profile.png` | Nodes-per-chunk for the gold-standard 1.25k run |
| `outputs/process_complexity_heatmap.png` | Self-healing depth heatmap — red = dense/hard sections |
| `outputs/schema_suggestions.md` | Non-canonical LLM intent types, sorted by frequency |

Current config: `TEST_CHUNKS = [1250]` (Gold Standard baseline). Results are persisted to `data/analytics/metrics.db` and skipped on re-run.

---

## Repository Structure

```
process-extraction-kernel/
│
├── app.py                  # Streamlit enterprise UI
├── run_agent.py            # Single-invoice CLI runner
├── batch_runner.py         # Batch queue simulator
├── patch_logic.py          # Programmatic logic patching script
├── requirements.txt
│
├── src/
│   ├── agent/
│   │   ├── state.py        # APState TypedDict (invoice fields + audit_log)
│   │   ├── nodes.py        # Node executor (LLM smart nodes + deterministic pass-through)
│   │   ├── router.py       # Deterministic edge router (condition predicate table)
│   │   └── compiler.py     # build_ap_graph() — JSON → CompiledGraph
│   │
│   ├── main.py             # Process mining orchestration entry point
│   ├── llm_classifier.py   # LLM seam — Ollama, self-healing recursive splitter
│   ├── heuristic.py        # Regex classifier + graph builder (CPU fallback, alias maps)
│   ├── ontology.py         # Canonical intent ontology + validation sets
│   ├── models.py           # Typed dataclasses (ProcessDoc, Node, Edge, Action…)
│   ├── mermaid.py          # ProcessDoc → Mermaid.js serializer
│   ├── gap_analyzer.py     # Sub-doc vs Master Manual shadow process audit
│   ├── benchmarker.py      # Chunk-size grid-search + analytics
│   ├── visualizer.py       # Charts: performance curve, heatmap, density profile
│   └── database.py         # SQLite metrics persistence
│
├── outputs/
│   ├── ap_master_manual_auto.json         # Extracted process graph (source)
│   ├── ap_master_manual_auto_patched.json # Patched graph with guardrails (used at runtime)
│   ├── ap_master_manual_auto.mmd          # Mermaid flowchart (open in VS Code)
│   └── *.png                              # Benchmarker analytics charts
│
└── data/
    ├── examples/                          # Source SOP documents (.txt)
    └── analytics/
        ├── metrics.db                     # SQLite metrics store (never wiped)
        └── schema_suggestions.json        # Live ontology miss counter
```

### Key module responsibilities

| Module | Role |
|--------|------|
| `src/agent/compiler.py` | Reads the patched JSON, deduplicates edges, wires conditional and unconditional edges, returns a `CompiledGraph` |
| `src/agent/router.py` | A lookup table of condition-string → predicate lambdas; evaluated in edge order; falls back to decision-type routing |
| `src/agent/nodes.py` | `ENTER_RECORD` and `VALIDATE_FIELDS` call `ChatOllama`; all other intents are pure deterministic state transitions |
| `patch_logic.py` | Reads the base JSON, applies ordered patches, writes a new JSON — re-runnable and version-controlled |
| `app.py` | Caches the compiled graph with `@st.cache_resource`; session history in `st.session_state` |

---

## Design Principles

> **Zero Hallucination at the Decision Layer**
>
> The LangGraph router is a pure function of the current `APState`. It reads a lookup table of
> condition predicates — no LLM, no probability, no ambiguity. A `$45,000` invoice with
> `po_match=True` will always route to `ESCALATE_TO_DIRECTOR`. Always.

> **100% Auditable**
>
> Every node that executes appends to `APState.audit_log`. The final state always contains
> the complete sequence of decisions made — which LLM extracted what, which gateway fired which
> branch, which guardrail was triggered. The Streamlit UI surfaces this as a labelled timeline.

> **Separation of Mining and Execution**
>
> Process mining (Phases 1–2) runs once and produces a JSON artifact. Execution (Phase 3+)
> reads that artifact. If the SOP changes, re-run the miner and re-patch. The agent code
> never needs to change.

---

## Mermaid Visualization

Install the **yzane.mermaid-editor** extension in VS Code to preview `.mmd` files directly. Open `outputs/ap_master_manual_auto.mmd` and use the split-preview panel.

| Color | Shape | Meaning |
|-------|-------|---------|
| Green `#9f9` | Circle `(( ))` | Start event |
| Blue `#bbf` | Rectangle `[ ]` | Action / Task node |
| Orange `#fdb` | Diamond `{ }` | Decision / Gateway |
| Red `#f99` | Rounded box `( )` | End event |
