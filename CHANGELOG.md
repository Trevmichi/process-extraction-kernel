# Changelog

All entries are grounded in commits from `docs/_git_log_stat.txt`.

---

## 2026-03-03 -- Correctness Hardening + Eval Harness

- **Condition DSL AND extension**: extended grammar to support
  `comparison (AND comparison)*`; guarded the n3 `has_po == false` edge with
  `status != "BAD_EXTRACTION" AND status != "MISSING_DATA" AND has_po == false`,
  resolving AMBIGUOUS_ROUTE when extraction fails on no-PO invoices.
  ([commit 6a697e4])

- **Gold invoice dataset + eval harness**: 30 gold invoices across 5 vendors
  and 3 scenarios, with `eval_runner.py` supporting mock and live modes.
  Achieves 30/30 terminal accuracy and 90/90 field accuracy.
  ([commit 1c13717])

- **Stability hardening**: verifier PO regex fix, router audit logging,
  normalizer and linter improvements, state schema formalization.
  ([commit 6c46331])

- **Invariants, conditions, linter, normalizer, verifier**: introduced
  `src/conditions.py` (eval-free condition DSL), `src/linter.py` (graph
  validation), `src/invariants.py` (structural checks),
  `src/normalize_graph.py` (15 idempotent repair passes), and
  `src/verifier.py` (evidence-backed extraction validation). Added 600+
  tests.
  ([commit 021913e])

- **Added .gitignore entries** for generated eval outputs and runtime routing
  logs.
  ([commit c7b2df9])

---

## 2026-03-01 -- v1.0 Release

- **LangGraph agent integration**: created `src/agent/` module with compiler,
  nodes, router, and state. Added Streamlit UI (`app.py`), batch runner
  (`batch_runner.py`), CLI runner (`run_agent.py`), and dynamic logic
  patching (`patch_logic.py`). Tagged as v1.0.
  ([commit d3b89df])

- **Production extraction finalization**: gap analysis reporting, benchmarker,
  schema suggestions, README update.
  ([commit 50427e6])

- **Agent node improvements**: minor fixes to `src/agent/nodes.py`.
  ([commit a184fec])

---

## 2026-02-28 -- Initial Development

- **Project initialization**: `.gitignore`, README, data collection and
  analysis infrastructure.
  ([commit ee3deff], [commit b2e5507], [commit 47bf86f])

- **Rapid prototyping**: heuristic extraction engine (`src/heuristic.py`),
  canonical ontology (`src/ontology.py`), LLM classifier with self-healing
  recursive splitter (`src/llm_classifier.py`), 5 test documents.
  ([commit afbe25f] through [commit a05623a])
