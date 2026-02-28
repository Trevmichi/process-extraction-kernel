from pathlib import Path

from src.render import to_json
from src.mermaid import to_mermaid
from src.trace import trace_event
from src.referee import referee_add_unknowns
from src.diff_tool import write_diff
from src.canonicalize import canonicalize_manual_to_explicit


from src.branch_model import apply_branch_model
def write_outputs(proc, out_json: str, out_mmd: str):
    # Apply manual canonicalization only to non-auto outputs
    if "_auto" not in out_json:
        canonicalize_manual_to_explicit(proc)
        print(f"[CANON] applied to {out_json} | nodes={len(proc.nodes)} edges={len(proc.edges)}")
    Path(out_json).write_text(to_json(proc), encoding="utf-8")
    Path(out_mmd).write_text(to_mermaid(proc), encoding="utf-8")


def run_one_manual(source_id: str, extractor, input_path: str, out_json: str, out_mmd: str, out_trace: str):
    text = Path(input_path).read_text(encoding="utf-8")
    trace_event(out_trace, "RECEIVE_INPUT", {"source_id": source_id, "path": input_path, "mode": "manual"})

    proc = extractor(text)
    errors = []
    added = referee_add_unknowns(proc)

    apply_branch_model(proc)
    write_outputs(proc, out_json, out_mmd)
    return errors, added


def run_one_heuristic(source_id: str, input_path: str, out_json: str, out_mmd: str, out_trace: str):
    text = Path(input_path).read_text(encoding="utf-8")
    trace_event(out_trace, "RECEIVE_INPUT", {"source_id": source_id, "path": input_path, "mode": "heuristic"})

    from src.heuristic import heuristic_extract_ap
    proc = heuristic_extract_ap(text, source_id=source_id, process_id=f"ap_{source_id}_auto")

    errors = []
    added = referee_add_unknowns(proc)

    apply_branch_model(proc)
    write_outputs(proc, out_json, out_mmd)
    return errors, added


def main():
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/traces").mkdir(parents=True, exist_ok=True)

    # Manual extractors (you already have these in src/extract.py)
    from src.extract import (
        manual_extract_doc_001, manual_extract_doc_002, manual_extract_doc_003,
        manual_extract_doc_004, manual_extract_doc_005,
    )

    manual_jobs = [
        ("doc_001", manual_extract_doc_001, "data/examples/doc_001.txt"),
        ("doc_002", manual_extract_doc_002, "data/examples/doc_002.txt"),
        ("doc_003", manual_extract_doc_003, "data/examples/doc_003.txt"),
        ("doc_004", manual_extract_doc_004, "data/examples/doc_004.txt"),
        ("doc_005", manual_extract_doc_005, "data/examples/doc_005.txt"),
    ]

    manual_paths = {}
    auto_paths = {}

    print("=== MANUAL EXTRACTS ===")
    for source_id, extractor, in_path in manual_jobs:
        out_json = f"outputs/ap_{source_id}.json"
        out_mmd  = f"outputs/ap_{source_id}.mmd"
        out_trace = f"outputs/traces/run_{source_id}.jsonl"

        errors, added = run_one_manual(source_id, extractor, in_path, out_json, out_mmd, out_trace)
        manual_paths[source_id] = out_json

        if errors:
            print(f"{source_id}: Validation errors:")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"{source_id}: OK -> {out_json}, {out_mmd} (referee added {len(added)} unknowns)")

    print("\n=== HEURISTIC EXTRACTS (AUTO) ===")
    for source_id, _, in_path in manual_jobs:
        out_json = f"outputs/ap_{source_id}_auto.json"
        out_mmd  = f"outputs/ap_{source_id}_auto.mmd"
        out_trace = f"outputs/traces/run_{source_id}_auto.jsonl"

        errors, added = run_one_heuristic(source_id, in_path, out_json, out_mmd, out_trace)
        auto_paths[source_id] = out_json

        if errors:
            print(f"{source_id}_auto: Validation errors:")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"{source_id}_auto: OK -> {out_json}, {out_mmd} (referee added {len(added)} unknowns)")

    # Auto-only docs (no manual extractor counterpart)
    auto_only_jobs = [
        ("ap_master_manual", "data/examples/ap_master_manual.txt"),
    ]
    for file_id, in_path in auto_only_jobs:
        out_json = f"outputs/{file_id}_auto.json"
        out_mmd  = f"outputs/{file_id}_auto.mmd"
        out_trace = f"outputs/traces/run_{file_id}_auto.jsonl"

        errors, added = run_one_heuristic(file_id, in_path, out_json, out_mmd, out_trace)
        auto_paths[file_id] = out_json

        if errors:
            print(f"{file_id}_auto: Validation errors:")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"{file_id}_auto: OK -> {out_json}, {out_mmd} (referee added {len(added)} unknowns)")

    doc_ids = [source_id for source_id, _, _ in manual_jobs] + ["ap_master_manual"]

    print("\n=== DIFFS: MANUAL vs AUTO ===")
    for file_id in doc_ids:
        if file_id == "ap_master_manual":
            print("Skipping diff for master manual (auto-only)")
            continue
        a = manual_paths[file_id]
        b = auto_paths[file_id]
        out_json = f"outputs/diff_{file_id}_manual_vs_auto.json"
        out_md   = f"outputs/diff_{file_id}_manual_vs_auto.md"
        write_diff(a, b, out_json, out_md, label_a=f"{file_id}_manual", label_b=f"{file_id}_auto")
        print(f"{file_id}: wrote {out_md}")

    print("\nAll runs OK.")


if __name__ == "__main__":
    main()



