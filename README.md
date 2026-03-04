# Process Extraction Kernel

A deterministic AP invoice-processing kernel. A mined process graph is patched
with business-logic guardrails, normalized through 15 idempotent repair passes,
validated by a structural linter, and compiled to a LangGraph state machine.
LLM calls are constrained to two extraction tasks
(see `src/agent/nodes.py: execute_node`); all routing decisions are made by an
eval-free condition DSL and a 2-phase deterministic router. Extraction output is
cross-checked against raw invoice text by an evidence-backed verifier.

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

# 7. Process a single invoice (requires Ollama)
python run_agent.py

# 8. Launch Streamlit UI (requires Ollama)
streamlit run app.py
```

---

## Documentation

| Document | Contents |
|----------|----------|
| [Architecture](docs/ARCHITECTURE.md) | Pipeline diagram, subsystem reference (normalizer, DSL, router, verifier, linter) |
| [Project History](docs/PROJECT_HISTORY.md) | Era-based timeline grounded in git log |
| [Evaluation Harness](docs/EVALUATION.md) | 50 gold invoices, evidence grounding rules, mock dispatch, metrics |
| [Changelog](CHANGELOG.md) | Milestone list with commit citations |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Gemma 3:12b via [Ollama](https://ollama.com) |
| Graph execution | [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`) |
| Condition engine | Eval-free DSL (`src/conditions.py`) |
| Web UI | [Streamlit](https://streamlit.io) |
| Runtime | Python 3.11+, fully local (no cloud API calls) |

---

## Current Metrics

- **648** tests passing
- **50/50** terminal accuracy (eval harness, mock mode)
- **150/150** field accuracy (3 fields x 50 invoices)
- **0** linter errors on production graph
