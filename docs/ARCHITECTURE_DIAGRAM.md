# Deterministic AI Workflow Architecture — Technical Detail

> Detailed trust-boundary and runtime diagram.
> For a scannable overview, see [ARCHITECTURE_OVERVIEW.md](ARCHITECTURE_OVERVIEW.md).
> For module-level documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart TD
    %% ═══════════════════════════════════════════════
    %% LANE 1 — Build-Time Workflow Preparation
    %% ═══════════════════════════════════════════════
    subgraph BUILD["Build-Time Workflow Preparation"]
        direction LR
        SRC(["Source Graph JSON"])
          --> PATCH["Patch Layer"]
          --> NORM["Normalize<br/>(17 passes)"]
          --> LINT["Lint / Invariants"]
          --> COMP["Compile"]
          --> WFG(["Executable<br/>Workflow Graph"])
    end

    %% ═══════════════════════════════════════════════
    %% LANE 2 — Runtime Extraction & Trust Boundary
    %% ═══════════════════════════════════════════════
    WFG -. "compiled artifact<br/>powers runtime" .-> ENTER

    subgraph EXTRACT["Runtime Extraction & Trust Boundary"]
        INV["Invoice Text"] --> ENTER["Invoice Intake<br/>(ENTER_RECORD)"]
        ENTER --> LLM["LLM Extraction<br/><i>untrusted · mock-patchable</i>"]

        subgraph TRUST["4-Layer Trust Boundary"]
            T1["Structural Validation"]
              --> T2["Semantic Validation"]
              --> T3["JSON Schema Gate"]
              --> T4["Evidence Verifier"]
        end

        LLM --> T1
        T4 --> ARITH["Arithmetic Cross-Check<br/><i>document consistency</i>"]
        ARITH -- "TRUST BARRIER" --> PROMOTE["Promote Verified Data"]
        PROMOTE --> STATE(["APState"])

        T4 -. "failure codes" .-> RETRY["CRITIC_RETRY<br/>(forensic, up to 2x)"]
        ARITH -. "failure codes" .-> RETRY
        RETRY -- "codes + context<br/>fed back to LLM" --> LLM
        RETRY -. "exhausted" .-> EXC["Manual Review /<br/>Exception Path"]
    end

    %% ═══════════════════════════════════════════════
    %% LANE 3 — Runtime Routing & Outcome
    %% ═══════════════════════════════════════════════
    STATE --> RTR

    subgraph ROUTE["Runtime Routing & Outcome"]
        RTR["2-Phase Deterministic Router"]
        RTR --> NEXT["Next Workflow Node"]
        RTR -. "fail-closed" .-> AMB["Ambiguous Route Review<br/><i>operator review</i>"]
        RTR -. "fail-closed" .-> NOR["No Route Review<br/><i>operator review</i>"]
    end

    %% ═══════════════════════════════════════════════
    %% LANE 4 — Observability, Interpretation & Eval
    %% ═══════════════════════════════════════════════
    STATE --> ALOG

    subgraph OBS["Observability, Interpretation & Evaluation"]
        subgraph TRACES["Runtime Traces"]
            ALOG[("Audit Log<br/>structured events on APState")]
        end

        subgraph INTERP["Typed Interpretation"]
            PARSE["Audit Parser<br/>(14 typed events)"]
              --> EXPL["Explanation Engine"]
        end

        subgraph SURF["Operator & Evaluation Surfaces"]
            OPUI["Operator UI"]
            EVALH["Eval Harness<br/>(126 records / 4 buckets)"]
        end

        ALOG --> PARSE
        EXPL --> OPUI
        EXPL --> EVALH
    end

    %% ═══════════════════════════════════════════════
    %% SIDECARS — cross-cutting influences
    %% ═══════════════════════════════════════════════
    POL(["PolicyConfig"]):::sidecar
      -. "cross-cutting config" .-> RTR
    POL -. "validation rules" .-> T1
    POL -. "station wiring" .-> PATCH

    SCHC(["Schema Contracts<br/><i>runtime enforcement + tests</i>"]):::sidecar
      -. "runtime enforcement" .-> T3

    %% ═══════════════════════════════════════════════
    %% STYLES
    %% ═══════════════════════════════════════════════
    classDef untrusted fill:#ffeaea,stroke:#d32f2f,stroke-width:3px,stroke-dasharray:5 5
    classDef barrier fill:#e8f5e9,stroke:#2e7d32,stroke-width:3px
    classDef failclosed fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef sidecar fill:#fafafa,stroke:#9e9e9e,stroke-dasharray:4 4

    class LLM untrusted
    class PROMOTE barrier
    class AMB,NOR,EXC failclosed

    style TRUST fill:#f1f8e9,stroke:#558b2f,stroke-width:2px
```

## Reading the Diagram

| Visual cue | Meaning |
|-----------|---------|
| Red dashed border | Untrusted AI output (LLM extraction) |
| Green subgraph | 4-layer trust boundary — deterministic validation stack |
| Green node | Trust barrier — only verified data crosses into state |
| Orange nodes | Fail-closed exits — always route to operator review, never silently drop |
| Dashed arrows | Failure paths, cross-cutting influences, or conceptual links |
| "TRUST BARRIER" edge | The hard boundary between untrusted extraction and trusted state |

## Design Decisions

- **Arithmetic is adjacent to, not inside, the trust boundary.** The 4-layer boundary validates extraction output (is the data correct?). Arithmetic validates the source document (do the numbers add up?). These are conceptually different checks.
- **CRITIC_RETRY re-enters the full pipeline.** Failure codes from any validation step are fed back to the LLM. The retry is forensic — it doesn't skip validation, it repeats it entirely.
- **Eval exercises the full deterministic stack.** The LLM box is mock-patchable — eval replaces only the AI, the entire validation + routing pipeline runs unchanged.
- **PolicyConfig is a cross-cutting sidecar.** It influences build-time patching, runtime validation, and routing decisions, but is not on the main data path.
