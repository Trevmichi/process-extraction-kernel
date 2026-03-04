# Project History

An era-based timeline of the process-extraction-kernel repository, grounded in git
history (`docs/_git_log_stat.txt`) and current source code.

---

## Era 1: Rapid Prototyping (Feb 28 2026, 00:56 -- 10:06)

**Goal**: Explore process-mining-from-text using heuristics and a local LLM.

**Commits** (7):
`afbe25f`, `df66e3e`, `376d4cf`, `570fe05`, `20b5f27`, `717ae3b`, `a05623a`

**What changed**:

- Built a heuristic extraction engine that reads policy text and classifies
  sentences against a canonical ontology of action/decision types
  (see `src/heuristic.py`, `src/ontology.py`, `src/models.py`).
- Added an LLM-backed classifier (`src/llm_classifier.py`) with a self-healing
  recursive text splitter: if the LLM returns zero intents for a chunk, the
  engine halves the chunk and retries.
- Produced JSON process graphs and Mermaid flowcharts for 5 test documents
  (`outputs/ap_doc_001*.json` through `outputs/ap_doc_005*.json`).
- Graph diff tooling (`src/diff_tool.py`) to compare manual vs auto extraction.

**Key files introduced**:
`src/heuristic.py`, `src/ontology.py`, `src/models.py`, `src/llm_classifier.py`,
`src/mermaid.py`, `src/extract.py`, `src/diff_tool.py`

---

## Era 2: Project Stabilization (Feb 28 2026, 12:44 -- 14:14)

**Goal**: Formalize the repository and add monitoring/analytics infrastructure.

**Commits** (3):
`ee3deff`, `b2e5507`, `47bf86f`

**What changed**:

- Formal "Initial commit of process extraction engine" ([commit ee3deff])
  established `.gitignore`, README, and project structure.
- Added stress-test data (`data/ap_heavy_stress.txt`) and input documents
  (`data/input/`).
- Built monitoring and analytics subsystems: SQLite metrics store
  (`src/database.py`), monitoring hooks (`src/monitor.py`), visualization
  charts (`src/visualizer.py`), and calibration runner (`src/calibrator.py`).
- Created gap analysis framework (`src/gap_analyzer.py`) to compare
  sub-documents against the master manual.

**Key files introduced**:
`src/database.py`, `src/monitor.py`, `src/visualizer.py`, `src/calibrator.py`,
`src/gap_analyzer.py`, `data/ap_heavy_stress.txt`

---

## Era 3: LangGraph Agent + v1.0 Release (Mar 01 2026)

**Goal**: Replace heuristic-only execution with a compiled LangGraph state machine
backed by bounded LLM micro-agents.

**Commits** (3):
`50427e6`, `d3b89df`, `a184fec`

**What changed**:

- **Architecture shift** ([commit d3b89df]): created `src/agent/` module with:
  - `compiler.py` -- reads process JSON and compiles it to a LangGraph
    `CompiledGraph`.
  - `nodes.py` -- node executor with LLM-backed "smart nodes" (ENTER_RECORD,
    VALIDATE_FIELDS) and deterministic pass-through nodes.
  - `router.py` -- deterministic edge router using a condition-predicate
    lookup table.
  - `state.py` -- `APState` TypedDict with audit log accumulator.
- **Dynamic logic patching** ([commit d3b89df]): `patch_logic.py` injects
  guardrail nodes and edges into the JSON graph before compilation, including
  an amount threshold gateway ($10,000) and a bad-data rejection path.
- **Streamlit UI** ([commit d3b89df]): `app.py` provides a browser-based
  dashboard with invoice input, execution trace, metric cards, and audit log.
- **Batch runner** ([commit d3b89df]): `batch_runner.py` processes a queue of
  invoices through the compiled graph.
- **CLI runner** ([commit d3b89df]): `run_agent.py` for single-invoice
  execution from the command line.
- **Production finalization** ([commit 50427e6]): benchmarker
  (`src/benchmarker.py`), schema suggestions, updated README.
- **Agent node fix** ([commit a184fec]): minor improvements to
  `src/agent/nodes.py`.

**Key files introduced**:
`src/agent/compiler.py`, `src/agent/nodes.py`, `src/agent/router.py`,
`src/agent/state.py`, `patch_logic.py`, `app.py`, `batch_runner.py`,
`run_agent.py`, `requirements.txt`

---

## Era 4: Correctness Hardening (Mar 03 2026)

**Goal**: Eliminate runtime ambiguity through static validation, evidence-backed
verification, and a deterministic eval harness.

**Commits** (5):
`021913e`, `6c46331`, `1c13717`, `6a697e4`, `c7b2df9`

### 4a. Invariants, Conditions, Linter, Normalizer, Verifier ([commit 021913e])

- **Condition DSL** (`src/conditions.py`): a safe, eval-free condition language
  with an explicit tokenizer, AST (`Comparison`), and interpreter. Supports
  `==`, `!=`, `>`, `>=`, `<`, `<=` operators plus boolean/numeric/string
  literals.
- **Graph linter** (`src/linter.py`): `lint_process_graph()` validates
  referential integrity, gateway semantics, and condition parseability.
  `assert_graph_valid()` blocks compilation on any error-severity issue.
- **Invariant system** (`src/invariants.py`): structural checks for match-split
  patterns, placeholder conditions, match_result ownership, and synthetic
  metadata completeness.
- **Normalizer** (`src/normalize_graph.py`): 15 idempotent repair passes that
  transform a raw extracted graph into a valid, lintable form. Each pass
  returns `(dict, list[str])` -- the repaired graph and a changelog.
- **Evidence-backed verifier** (`src/verifier.py`): `verify_extraction()`
  cross-checks LLM extraction output against raw invoice text. Per-field
  checks for vendor, amount, and has_po. Amount disambiguation via 30-char
  keyword window.
- **Comprehensive test suite**: `tests/test_conditions.py`,
  `tests/test_linter.py`, `tests/test_normalize.py`, `tests/test_verifier.py`,
  `tests/test_patch.py`, `tests/test_batch_smoke.py`,
  `tests/test_production_graph_regressions.py`,
  `tests/test_router_fail_closed.py`, and others.

### 4b. Stability Hardening ([commit 6c46331])

- Router upgraded to use DSL-compiled predicates with caching via
  `get_predicate()` (see `src/agent/router.py`).
- Verifier integrated into ENTER_RECORD node execution
  (see `src/agent/nodes.py`).
- State model formalized with `extraction`, `provenance`, `match_3_way`, and
  `match_result` fields (see `src/agent/state.py`).
- Normalization pipeline called automatically by `patch_logic.py` after
  patching.
- Additional tests for router audit logging and state schema validation.

### 4c. Gold Invoice Dataset + Eval Harness ([commit 1c13717])

- 30 manually-authored gold invoices across 5 vendors and 3 scenarios
  (happy_path, no_po, match_fail) in `datasets/gold_invoices/`.
- Ground-truth expected outputs in `datasets/expected.jsonl`.
- Schema documentation in `datasets/schema.md`.
- Eval runner (`eval_runner.py`) supporting mock mode (deterministic,
  no LLM) and live mode (Ollama). Reports terminal accuracy, field accuracy,
  and confusion matrix.
- Eval harness tests in `tests/test_eval_harness.py` including evidence
  grounding validation.

### 4d. DSL AND Extension + Routing Fix ([commit 6a697e4])

- Extended condition DSL grammar to support AND-chains:
  `comparison (AND comparison)*`.
- Added `Conjunction` AST node with flat `tuple[Comparison, ...]` children.
- Guarded the n3 `has_po == false` edge with a compound condition:
  `status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false`,
  resolving an AMBIGUOUS_ROUTE when extraction fails on no-PO invoices.
- Router dominance regression tests in `tests/test_batch_smoke.py`.

### 4e. Housekeeping ([commit c7b2df9])

- Added `.gitignore` entries for generated eval outputs (`eval_report.json`,
  `eval_report.md`) and runtime routing logs (`outputs/unmodeled_logic.jsonl`).

**Current state**: 637 tests passing, 30/30 terminal accuracy,
90/90 field accuracy, 0 linter errors on production graph.
