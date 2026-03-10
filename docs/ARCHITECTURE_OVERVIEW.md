# Architecture Overview

> Scannable overview of the deterministic AI workflow for invoice processing.
> For the detailed technical view, see [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md).
> For module-level documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart TD
    subgraph BUILD_TIME["Build-Time"]
        direction LR
        SRC(["Source Graph"]) --> BUILD["Build Pipeline"] --> WFG(["Executable Workflow Graph"])
    end

    WFG -. "compiled workflow" .-> LLM

    INV(["Invoice Text"]) --> LLM["LLM Extraction"]:::untrusted
    LLM -- "untrusted output" --> VAL["Deterministic Validation"]:::deterministic
    VAL -- "verified data" --> STATE(["APState"])

    VAL -. "failure codes" .-> RETRY["Forensic Retry"]:::failclosed
    RETRY -- "codes + context" --> LLM
    RETRY -. "exhausted" .-> EXC["Exception Path"]:::failclosed

    STATE --> RTR["Fail-Closed Router"]:::deterministic
    RTR --> NEXT["Workflow Continues"]
    RTR -. "fail-closed" .-> EXC

    STATE -. "audit events" .-> INTERP["Audit & Explanation"]
    INTERP --> OPUI["Operator UI"]
    INTERP --> EVAL["Eval Harness"]

    classDef untrusted fill:#ffeaea,stroke:#d32f2f,stroke-width:2px,stroke-dasharray:5 5
    classDef deterministic fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    classDef failclosed fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

## Reading the Diagram

| Visual cue | Meaning |
|------------|---------|
| Red dashed border | Untrusted AI output |
| Green border | Deterministic control (validation, routing) |
| Orange border | Failure handling (retry, fail-closed exits) |
| Stadium shapes | External inputs or data stores |
| Dashed arrows | Failure paths, artifact/runtime links, or observability flows |

Cross-cutting concerns (PolicyConfig, Schema Contracts) and internal validation steps (structural, semantic, schema gate, evidence verifier, arithmetic) are detailed in the [technical diagram](ARCHITECTURE_DIAGRAM.md).
