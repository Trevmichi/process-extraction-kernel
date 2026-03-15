# Discovery Lab

This directory is an offline research sandbox for entropy reduction in the process-extraction-kernel.

## Purpose

The discovery sandbox exists to propose candidate deterministic rules and candidate microkernels from:
- gold invoice cohorts
- runtime behavior comparisons
- constrained perturbations
- future surrogate modeling and optimization experiments

Its job is not to make live routing decisions.
Its job is to help discover, score, and package candidate deterministic improvements that can later be reviewed and merged into the main system.

## Core Design Principle

This sandbox may observe the deterministic system, but the deterministic system must not depend on this sandbox.

That means:
- discovery code may read datasets, eval outputs, verifier outputs, and schema definitions
- production runtime code must not import or depend on discovery modules
- discovery outputs must be reviewable artifacts, not direct production mutations

## Non-Goals

This lab is not part of the live routing path.

It must not:
- directly modify production routing behavior
- bypass verifier, referee, schema gates, or trust boundaries
- auto-write into core invariants or router logic without review
- become a required dependency for production runtime

## Inputs

The lab may read from:
- `datasets/gold_invoices/`
- `datasets/expected.jsonl`
- evaluation outputs and reports
- verifier / referee results
- synthetic invoice scaffolds
- schema and ontology definitions

## Outputs

The lab may produce:
- candidate invariant reports
- generated regression tests
- suggested patches
- draft microkernels
- run summaries
- structured evidence bundles

## Initial Scope

The first phase should stay narrow and interpretable.

Preferred early targets:
- PO-presence cohorts
- amount-threshold cohorts
- duplicate-total ambiguity
- tax/subtotal/total consistency edge cases
- vendor alias normalization patterns

The first implementation should prioritize:
- cohort slicing
- structured feature extraction
- gold-vs-runtime comparisons
- constrained perturbations
- candidate scoring

before introducing heavier probabilistic tooling such as Gaussian Processes or Bayesian Optimization.

## Directory Expectations

This sandbox should remain organized around offline experimentation and reviewable outputs.

Expected contents include:
- configs
- cohort loaders
- feature extraction
- oracle adapters
- candidate scoring
- constrained probes
- report exporters
- output bundles

## Promotion Rule

Nothing from this lab should be treated as production truth unless it is converted into deterministic artifacts, covered by tests, and reviewed before merging.
