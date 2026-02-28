import os
import time
from pathlib import Path

from src.render import to_json
from src.mermaid import to_mermaid
from src.trace import trace_event
from src.referee import referee_add_unknowns
from src.diff_tool import write_diff
from src.canonicalize import canonicalize_manual_to_explicit
from src.database import log_extraction, get_performance_trends


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
    return errors, added, proc, len(text)


def run_one_heuristic(source_id: str, input_path: str, out_json: str, out_mmd: str, out_trace: str, gap_report: str = ""):
    text = Path(input_path).read_text(encoding="utf-8")
    trace_event(out_trace, "RECEIVE_INPUT", {"source_id": source_id, "path": input_path, "mode": "heuristic"})

    from src.heuristic import heuristic_extract_ap
    proc = heuristic_extract_ap(text, source_id=source_id, process_id=f"ap_{source_id}_auto", gap_report=gap_report)

    errors = []
    added = referee_add_unknowns(proc)

    apply_branch_model(proc)
    write_outputs(proc, out_json, out_mmd)
    return errors, added, proc, len(text)


def main():
    # Selectively delete generated artifacts from outputs/ so every run is
    # fresh.  Only .json, .mmd, and .png files are removed.
    # data/analytics/ (metrics.db, master_audit_log.csv) is NEVER touched.
    _outputs = Path("outputs")
    _outputs.mkdir(exist_ok=True)
    _deleted = 0
    for _ext in ("*.json", "*.mmd", "*.png"):
        for _f in _outputs.glob(_ext):
            _f.unlink()
            _deleted += 1
    if _deleted:
        print(f"[main] Cleaned {_deleted} generated artifact(s) from outputs/ - starting clean.")
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

        errors, added, proc, char_count = run_one_manual(source_id, extractor, in_path, out_json, out_mmd, out_trace)
        manual_paths[source_id] = out_json
        log_extraction(source_id, "manual", len(proc.nodes), len(proc.edges), len(proc.unknowns), char_count)

        if errors:
            print(f"{source_id}: Validation errors:")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"{source_id}: OK -> {out_json}, {out_mmd} (referee added {len(added)} unknowns)")

    _llm_mode   = os.environ.get("USE_LLM_CLASSIFIER") == "true"
    _model_name = "llm:gemma3:12b" if _llm_mode else "heuristic"
    _COOLDOWN_SEC = 2  # VRAM cool-down between LLM chunks (ignored in heuristic mode)

    print("\n=== HEURISTIC EXTRACTS (AUTO) ===")
    for idx, (source_id, _, in_path) in enumerate(manual_jobs):
        out_json = f"outputs/ap_{source_id}_auto.json"
        out_mmd  = f"outputs/ap_{source_id}_auto.mmd"
        out_trace = f"outputs/traces/run_{source_id}_auto.jsonl"

        # Cool-down between documents in LLM mode to let VRAM clear
        if _llm_mode and idx > 0:
            print(f"[cool-down] {_COOLDOWN_SEC}s VRAM cool-down ...")
            time.sleep(_COOLDOWN_SEC)

        errors, added, proc, char_count = run_one_heuristic(source_id, in_path, out_json, out_mmd, out_trace)
        auto_paths[source_id] = out_json
        log_extraction(f"{source_id}_auto", _model_name, len(proc.nodes), len(proc.edges), len(proc.unknowns), char_count)

        if errors:
            print(f"{source_id}_auto: Validation errors:")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"{source_id}_auto: OK -> {out_json}, {out_mmd} (referee added {len(added)} unknowns)")

    # Auto-only docs (no manual extractor counterpart)
    # Load any existing gap report to feed back into the master manual extraction
    _gap_report_path = Path("outputs/gap_analysis_report.md")
    _gap_report = _gap_report_path.read_text(encoding="utf-8") if _gap_report_path.exists() else ""

    auto_only_jobs = [
        ("ap_master_manual", "data/examples/ap_master_manual.txt"),
    ]
    for file_id, in_path in auto_only_jobs:
        if _llm_mode:
            print(f"[cool-down] {_COOLDOWN_SEC}s VRAM cool-down ...")
            time.sleep(_COOLDOWN_SEC)
        out_json = f"outputs/{file_id}_auto.json"
        out_mmd  = f"outputs/{file_id}_auto.mmd"
        out_trace = f"outputs/traces/run_{file_id}_auto.jsonl"

        errors, added, proc, char_count = run_one_heuristic(file_id, in_path, out_json, out_mmd, out_trace, gap_report=_gap_report)
        auto_paths[file_id] = out_json
        log_extraction(f"{file_id}_auto", _model_name, len(proc.nodes), len(proc.edges), len(proc.unknowns), char_count)

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

    print("\n=== GAP ANALYSIS ===")
    from src.gap_analyzer import write_gap_analysis
    gap_report = write_gap_analysis("outputs")
    print(f"Gap analysis written to {gap_report}")

    print("\n=== PERFORMANCE TRENDS (last 5 runs) ===")
    get_performance_trends()

    print("\nAll runs OK.")


if __name__ == "__main__":
    main()



