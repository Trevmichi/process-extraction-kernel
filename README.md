# Process Extraction Kernel

A deterministic AP invoice-processing kernel. A mined process graph is patched
with business-logic guardrails, normalized through 15 idempotent repair passes,
validated by a structural linter, and compiled to a LangGraph state machine.
LLM calls are constrained to two extraction tasks
(see `src/agent/nodes.py: execute_node`); all routing decisions are made by an
eval-free condition DSL and a 2-phase deterministic router. Extraction output is
cross-checked against raw invoice text by an evidence-backed verifier. A 106-invoice
gold dataset with mock and live evaluation modes drives continuous accuracy tracking,
and a Gemini-powered meta-agent can autonomously patch failures and open PRs.

---

## Core Guarantees

| Guarantee | Enforcement |
|-----------|-------------|
| **Deterministic routing** -- no LLM at the decision layer | `src/agent/router.py: analyze_routing` evaluates DSL predicates, never calls an LLM |
| **Evidence-backed extraction** -- verifier cross-checks LLM output against raw text | `src/verifier.py: verify_extraction` returns failure codes + provenance |
| **Fail-closed** -- ambiguous or missing routes become exception stations | `src/agent/router.py: route_edge` resolves to exception sinks; `src/linter.py: assert_graph_valid` blocks compilation on errors |
| **No eval/exec in conditions** -- explicit tokenizer + AST | `src/conditions.py: parse_condition` produces `Comparison` / `Conjunction` AST nodes |
| **Full audit trail** -- per-step audit log on every invoice | `src/agent/state.py: APState.audit_log` accumulates via `Annotated[list, operator.add]` |

---

## Quickstart

```bash
# 1. Environment
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt

# 2. Start Ollama (needed for live LLM mode and UI)
ollama pull gemma3:12b && ollama serve

# 3. Run tests (no LLM needed)
python -m pytest tests/ -q

# 4. Generate patched graph (no LLM needed)
python patch_logic.py

# 5. Run eval harness in mock mode (no LLM needed)
python eval_runner.py

# 5b. Run full QA check (tests + eval, no LLM needed)
bash scripts/qa_eval.sh          # or: pwsh scripts/qa_eval.ps1

# 6. Run eval harness with live LLM
python eval_runner.py --live

# 6b. Run optional audit layer (requires Ollama or OpenAI key)
python eval_runner.py --audit --audit-sample 5

# 7. Process a single invoice (requires Ollama)
python run_agent.py

# 8. Launch Streamlit UI (requires Ollama)
streamlit run app.py

# 9. Dataset tooling (no LLM needed)
python scripts/check_dataset_quotas.py            # enforce coverage quotas
python scripts/scaffold_invoice.py --id INV-2100 --vendor "Acme" --amount 500 --has-po true --tags happy_path
python scripts/generate_synthetic_batch.py --count 50 --noise-level 0.02

# 10. Auto-optimizer meta-agent (requires GOOGLE_API_KEY + gh CLI)
python scripts/auto_optimizer.py --dry-run         # preview patch, no git changes
python scripts/auto_optimizer.py --sweep --limit 5  # fix up to 5 failures, branch/test/PR
```

---

## Project Structure

```
process-extraction-kernel/
├── app.py                  # Streamlit UI entry point
├── run_agent.py            # Single invoice CLI runner
├── batch_runner.py         # Batch processing runner
├── patch_logic.py          # Graph patching + normalization orchestration
├── eval_runner.py          # Evaluation harness (mock & live modes)
├── eval_triage.py          # Failure triage + action plans
├── eval_audit.py           # Audit layer for evidence trace data
├── eval_variance.py        # Variance analysis across runs
├── src/
│   ├── agent/
│   │   ├── compiler.py     # JSON → LangGraph compiler
│   │   ├── router.py       # 2-phase deterministic router
│   │   ├── nodes.py        # Node executors (ENTER_RECORD, VALIDATE_FIELDS, ROUTE_FOR_REVIEW)
│   │   └── state.py        # APState definition (extraction, provenance, audit_log)
│   ├── conditions.py       # Eval-free condition DSL (tokenizer, AST, compiler)
│   ├── linter.py           # Graph linter (sections A–E)
│   ├── invariants.py       # Structural invariant checks
│   ├── normalize_graph.py  # 15 idempotent repair passes
│   ├── verifier.py         # Evidence-backed extraction verifier
│   ├── unmodeled.py        # JSONL logger for unmodeled routing events
│   ├── extract.py          # LLM extraction pipeline
│   ├── canonicalize.py     # Invoice text canonicalization
│   ├── models.py           # Data models and types
│   ├── gap_analyzer.py     # Gap analysis reporting
│   └── ...                 # visualizer, benchmarker, calibrator, monitor, etc.
├── scripts/
│   ├── auto_optimizer.py        # Gemini meta-agent (triage → patch → test → PR)
│   ├── generate_synthetic_batch.py  # Procedural invoice generator + OCR noise
│   ├── scaffold_invoice.py      # Test case stub generator
│   ├── check_dataset_quotas.py  # Stratified coverage enforcement
│   ├── fix_graph.py             # Graph repair utility
│   ├── qa_eval.sh / qa_eval.ps1 # QA runner (tests + eval)
│   └── run_all.ps1              # Full system runner
├── tests/                  # 773 tests (pytest, no LLM needed)
├── datasets/
│   ├── expected.jsonl      # 106 gold records
│   ├── schema.md           # JSONL schema + evidence grounding rules
│   └── gold_invoices/      # 106 invoice text files
├── outputs/                # Patched graphs, traces, visualizations
├── docs/                   # Architecture, history, evaluation docs
├── schema/                 # Process schema definitions
├── data/                   # Analytics DB, example documents
└── .github/workflows/      # CI/CD (qa-eval.yml)
```

---

## Architecture Layers

| Layer | Module | Description |
|-------|--------|-------------|
| **Normalization** | `src/normalize_graph.py` | 15 idempotent repair passes: fix artifacts, canonical keys, edge conditions, gateways, exception nodes, deduplication |
| **Condition DSL** | `src/conditions.py` | Eval-free grammar: `comparison (AND comparison)*`; tokenizer → AST (`Comparison` / `Conjunction`) → compiled predicate |
| **Graph Linter** | `src/linter.py` + `src/invariants.py` | Sections A–E: referential integrity, actor/artifact checks, gateway semantics, decision consistency, structural invariants |
| **LangGraph Agent** | `src/agent/compiler.py` | Compiles patched JSON → `StateGraph`; calls `assert_graph_valid`, builds station map for router |
| **Deterministic Router** | `src/agent/router.py` | Strict 2-phase: conditional edges first, unconditional fallback; >1 match → AMBIGUOUS_ROUTE station; 0 matches → NO_ROUTE station |
| **Node Executors** | `src/agent/nodes.py` | ENTER_RECORD (LLM extraction), VALIDATE_FIELDS (LLM validation), ROUTE_FOR_REVIEW (structured audit + exception status) |
| **Evidence Verifier** | `src/verifier.py` | Cross-checks extracted fields against raw invoice text; returns failure codes + provenance metadata |
| **Exception Stations** | `patch_logic.py` | 4 fail-closed ROUTE_FOR_REVIEW nodes: bad_extraction, unmodeled_gate, ambiguous_route, no_route |
| **Unmodeled Logger** | `src/unmodeled.py` | JSONL logger for unmodeled routing events (never logs raw_text for privacy) |

---

## Evaluation Harness

The eval harness validates extraction accuracy against a stratified gold dataset.

| Component | Detail |
|-----------|--------|
| **Gold dataset** | 106 invoices in `datasets/expected.jsonl` + `datasets/gold_invoices/` |
| **Schema** | Documented in [`datasets/schema.md`](datasets/schema.md) |
| **Mock mode** | `python eval_runner.py` — deterministic mock LLM, no external calls |
| **Live mode** | `python eval_runner.py --live` — real Ollama LLM |
| **Audit mode** | `python eval_runner.py --audit --audit-sample N` — evidence trace analysis |
| **Filtering** | `python eval_runner.py --filter INV-1001,INV-2005` — fast iteration on specific invoices |
| **Triage** | `python eval_triage.py` — failure classification + action plans |
| **Variance** | `python eval_variance.py` — cross-run consistency analysis |

**Tag taxonomy** — each gold record has scenario tags for cohort analysis:

| Tag | Meaning |
|-----|---------|
| `happy_path` | Normal invoice with PO, amount under threshold |
| `no_po` | No purchase order reference |
| `match_fail` | PO exists but 3-way match fails |
| `bad_extraction` | Expected extraction failure |
| `missing_data` | Expected missing-data rejection |

**Evidence grounding** — all `mock_extraction` evidence strings must be verbatim
substrings of the invoice text. The verifier normalizes via `_normalize_text()`
(collapse whitespace, strip, casefold) before containment checks.

---

## Dataset Tooling

| Script | Purpose |
|--------|---------|
| `scripts/scaffold_invoice.py` | Generate a new test case stub (invoice text template + JSONL record) |
| `scripts/generate_synthetic_batch.py` | Procedural invoice generator with configurable OCR noise injection (`--count N --noise-level 0.02`) |
| `scripts/check_dataset_quotas.py` | Enforce stratified coverage rules to prevent happy-path metric padding (`--warn-only` for soft mode) |

Adding a new gold invoice:

1. Add a `.txt` file to `datasets/gold_invoices/`
2. Append a JSON line to `datasets/expected.jsonl`
3. Ensure all evidence strings are verbatim substrings of the invoice text
4. Validate: `python -m pytest tests/test_eval_harness.py::TestEvidenceGrounding -v`

---

## Auto-Optimizer Meta-Agent

`scripts/auto_optimizer.py` is an autonomous 4-stage pipeline that reads
`eval_report.json`, uses the Gemini API to generate patches for `src/verifier.py`,
tests them in a Git sandbox, and opens Pull Requests for passing patches.

| Stage | Name | Action |
|-------|------|--------|
| 1 | **Triage** | Parse `eval_report.json`, extract first (or all) failures with field mismatches and action plans |
| 2 | **Gemini Brain** | Call Gemini REST API (`gemini-3.1-pro-preview`) with failure context + current verifier source; receive patched code |
| 3 | **Git Crucible** | Create branch, write patch, run `pytest` (60s timeout); rollback on failure |
| 4 | **Delivery** | If tests pass: commit, push, `gh pr create --fill`. If not: hard reset + branch delete |

```bash
# Prerequisites
pip install requests
export GOOGLE_API_KEY="your-key-here"
gh auth login

# Dry run — review proposed patch, no git changes
python scripts/auto_optimizer.py --dry-run

# Fix first failure
python scripts/auto_optimizer.py

# Sweep mode — fix ALL failures, cap at 5
python scripts/auto_optimizer.py --sweep --limit 5
```

---

## CI / CD

GitHub Actions workflow (`.github/workflows/qa-eval.yml`) runs on every push to
`main` and on pull requests touching:

- `datasets/**`
- `eval_runner.py`
- `tests/test_eval_harness.py`
- `scripts/**`
- `docs/EVALUATION.md`

The workflow runs `bash scripts/qa_eval.sh` (pytest + eval harness in mock mode)
on Ubuntu with Python 3.11.

---

## Documentation

| Document | Contents |
|----------|----------|
| [Architecture](docs/ARCHITECTURE.md) | Pipeline diagram, subsystem reference (normalizer, DSL, router, verifier, linter) |
| [Project History](docs/PROJECT_HISTORY.md) | Era-based timeline grounded in git log |
| [Evaluation Harness](docs/EVALUATION.md) | Gold invoices, evidence grounding rules, mock dispatch, metrics |
| [Dataset Schema](datasets/schema.md) | JSONL schema, field comparison, tag taxonomy, mock dispatch rules |
| [Changelog](CHANGELOG.md) | Milestone list with commit citations |
| [Quality Gates](docs/QUALITY_GATES.md) | Validation sequences, PR checklist, mutation guidance, failure-pattern taxonomy |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Gemma 3:12b via [Ollama](https://ollama.com) |
| Graph execution | [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`) |
| Condition engine | Eval-free DSL (`src/conditions.py`) |
| Web UI | [Streamlit](https://streamlit.io) |
| Meta-agent LLM | Gemini 3.1 Pro Preview via REST API (`requests`) |
| CI | [GitHub Actions](https://github.com/features/actions) |
| Runtime | Python 3.11+ |

---

## Current Metrics

- **773** tests passing
- **106/106** terminal accuracy (eval harness, mock mode)
- **318/318** field accuracy (3 fields x 106 invoices)
- **0** linter errors on production graph

---

## License

MIT License — see [LICENSE](LICENSE).
