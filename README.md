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

## Hardware Calibration

The calibrator (`src/calibrator.py`) measures **Information Density** — unique canonical process nodes discovered per second — across four chunk-size thresholds (5k, 7.5k, 10k, 15k tokens). This identifies the optimal document granularity for your GPU and model combination.

### Running the calibrator

```bash
py -m src.calibrator
```

By default it tests against `data/ap_heavy_stress.txt`. Pass a different path as needed:

```python
from src.calibrator import test_batch_efficiency
test_batch_efficiency("data/examples/my_large_policy.txt")
```

### Analytics Dashboard

After a calibration run, generate the performance benchmark chart:

```bash
py -m src.visualizer
```

This produces `outputs/performance_benchmark.png` (dual-axis: TPS line + Unknown Count bars) and appends a `success_probability` column to `outputs/batch_report.csv`.

![Performance Benchmark](outputs/performance_benchmark.png)

### Output: `outputs/batch_report.csv`

| Column | Description |
|--------|-------------|
| `chunk_size_tokens` | Target chunk size (words ≈ tokens) |
| `doc_total_words` | Total words in the source document |
| `num_chunks` | Number of chunks the document was split into |
| `avg_effective_tokens` | Actual average words per chunk |
| `avg_unique_nodes` | Average unique canonical intents found per chunk |
| `avg_unknown_count` | Average unresolved unknowns per chunk |
| `avg_broken_edges` | Average edges referencing missing nodes per chunk |
| `node_recovery_rate` | `avg_unique_nodes / avg_effective_tokens` — local density |
| `logic_integrity` | Total broken edges across all chunks (0 = perfect) |
| `latency_per_1k_tokens` | Seconds per 1,000 tokens |
| `info_density` | `avg_unique_nodes / avg_elapsed_sec` — higher is better |
| `stitch_failures` | Inter-chunk handoffs where the last intent of chunk[i] was not seen in chunk[i+1] |
| `vram_delta_mb` | GPU VRAM change in MiB during the threshold run (-1 = not available) |
| `tps` | Tokens (words) processed per second for this threshold |
| `success_probability` | `avg_unique_nodes / doc_total_words` — global node yield |
| `sweet_spot` | `YES` on the row with the highest information density |

### Interpreting results for the RTX 5070

> **Tokens are approximated as whitespace-delimited words** (1 word ≈ 1 token). This is an intentional simplification — install a proper tokenizer if sub-word precision matters.

In LLM mode (`USE_LLM_CLASSIFIER=true`) the GPU is the bottleneck. Typical findings:

- **Small chunks (5k tokens):** Highest information density — more extraction passes, each with full context coverage.
- **Medium chunks (7.5k–10k tokens):** Peak raw throughput (TPS) — fewer round-trips, warm heuristic path.
- **Large chunks (15k tokens):** May hit Gemma 3:12b's context ceiling on very long documents, risking hallucination or truncation.

The `sweet_spot` column identifies the chunk size with the best `info_density`. Monitor `stitch_failures` to detect context loss at chunk boundaries.

**Breaking Point** is flagged when `avg_unknown_count` spikes ≥ 2× the previous threshold, indicating the model can no longer reliably resolve intents at that granularity.

---

## Knowledge Base

Persistent analytics data lives in `data/analytics/` and is **never wiped** by pipeline runs.

| File | Description |
|---|---|
| `data/analytics/metrics.db` | SQLite database — `extraction_logs` and `calibration_results` tables; survives every `main()` invocation |
| `data/analytics/master_audit_log.csv` | Watchdog audit log — one row per file processed by `src/monitor.py` |

---

## Output Files

Generated artifacts are written to `outputs/` on every run. Files matching `*.json`, `*.mmd`, and `*.png` are automatically deleted at the start of each `main()` invocation to guarantee a fresh extraction. `.csv`, `.md`, and `.jsonl` trace files are preserved between runs.

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
| `batch_report.csv` | Hardware calibration results — all metrics including TPS, stitch failures, success probability |
| `performance_benchmark.png` | Dual-axis analytics chart: TPS vs Unknown Count by chunk size |

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
│   ├── analytics/         # Persistent knowledge base (never wiped)
│   │   ├── metrics.db          # SQLite metrics (extraction_logs, calibration_results)
│   │   └── master_audit_log.csv  # Watchdog per-file audit history
│   ├── examples/          # Source policy documents (.txt)
│   └── input/             # Drop-zone for monitor.py watchdog
├── outputs/               # Generated artifacts (*.json/*.mmd/*.png wiped on each run)
│   └── traces/            # Execution trace logs (.jsonl, preserved)
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
│   ├── diff_tool.py       # Manual vs. auto graph differ
│   ├── database.py        # SQLite metrics store (log_extraction, get_performance_trends)
│   ├── calibrator.py      # Batch stress-test: TPS, stitch failures, breaking-point analysis
│   └── visualizer.py      # Analytics dashboard: dual-axis chart + success_probability
└── tests/
    └── test_validate.py
```
