"""
monitor.py
Production Automation Loop with Confidence Scoring.

Watchdog polls data/input/ for new .txt files every 10 seconds.
For each new file detected:
  1. Run heuristic extraction at the 5k-token chunk threshold.
  2. Compare Node Density against the Sweet Spot baseline in metrics.db.
  3. Assign a confidence status:
       GREEN  : Pass            — density ratio >= 0.8,  no stitch failures
       YELLOW : Logic Break     — density ratio >= 0.8,  stitch_failures > 0
       RED    : Low Confidence  — density ratio  < 0.8   (checked first)
  4. Regenerate outputs/performance_benchmark.png via visualizer.
  5. Append a row to data/analytics/master_audit_log.csv.
  6. Print a Status Report to the terminal.

Run:
    py -m src.monitor
or:
    from src.monitor import watchdog
    watchdog("data/input/")
"""
from __future__ import annotations

import csv
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

# Chunk size used for all watchdog extractions
_WATCH_CHUNK_SIZE = 5000

# Confidence threshold — below this ratio the file is flagged RED
_RED_THRESHOLD = 0.80

_DB_PATH = Path("data/analytics/metrics.db")

# ---------------------------------------------------------------------------
# Safety: directories the watchdog must NEVER monitor
# ---------------------------------------------------------------------------
_EXCLUDED_WATCH_DIRS: tuple[str, ...] = (
    "outputs",
    "data/analytics",
)
_AUDIT_CSV = Path("data/analytics/master_audit_log.csv")
_AUDIT_FIELDNAMES = [
    "timestamp", "filename", "total_words", "chunk_size",
    "total_unique_nodes", "node_density", "stitch_failures",
    "tps", "baseline_density", "confidence_ratio", "status",
]


# ---------------------------------------------------------------------------
# Baseline loader
# ---------------------------------------------------------------------------

def _load_baseline() -> Optional[Dict[str, Any]]:
    """
    Return the most recent sweet-spot calibration row from metrics.db,
    or None if no baseline exists yet.

    Keys returned: node_recovery_rate, info_density, chunk_size_tokens, doc_name
    """
    if not _DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT node_recovery_rate, info_density, chunk_size_tokens, doc_name
            FROM   calibration_results
            WHERE  sweet_spot = 1
            ORDER  BY id DESC
            LIMIT  1
            """
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Success Predictor
# ---------------------------------------------------------------------------

def success_predictor(
    node_density: float,
    stitch_failures: int,
    baseline_density: float,
) -> Tuple[str, float]:
    """
    Compare node_density against baseline_density and return
    (status_label, confidence_ratio).

    Priority order:
      1. confidence_ratio < RED_THRESHOLD  →  RED:    Low Confidence
      2. stitch_failures > 0              →  YELLOW: Logic Break
      3. otherwise                        →  GREEN:  Pass
    """
    confidence_ratio = (node_density / baseline_density) if baseline_density > 0 else 1.0

    if confidence_ratio < _RED_THRESHOLD:
        return "RED: Low Confidence", round(confidence_ratio, 4)
    if stitch_failures > 0:
        return "YELLOW: Logic Break", round(confidence_ratio, 4)
    return "GREEN: Pass", round(confidence_ratio, 4)


# ---------------------------------------------------------------------------
# Per-file extraction
# ---------------------------------------------------------------------------

def _extract_file(filepath: Path) -> Dict[str, Any]:
    """
    Run heuristic extraction at _WATCH_CHUNK_SIZE on *filepath*.

    Aggregates unique canonical keys across all chunks (global dedup),
    computes stitch failures at every chunk boundary, and returns a
    metrics dict ready for audit logging and confidence scoring.
    """
    from src.calibrator import _words_to_chunks, _run_extraction

    text = filepath.read_text(encoding="utf-8", errors="replace")
    words = text.split()
    total_words = len(words)

    chunks = _words_to_chunks(words, _WATCH_CHUNK_SIZE)

    all_unique_keys: Set[str] = set()
    chunk_results: list[Dict[str, Any]] = []
    total_elapsed = 0.0

    for idx, chunk in enumerate(chunks):
        t0 = time.perf_counter()
        m = _run_extraction(chunk, source_id=f"watch_{filepath.stem}_{idx}")
        total_elapsed += time.perf_counter() - t0
        all_unique_keys |= m["all_keys"]
        chunk_results.append(m)

    # Stitch failure: last canonical key of chunk[i] absent from chunk[i+1]
    stitch_failures = sum(
        1 for i in range(1, len(chunk_results))
        if chunk_results[i - 1]["last_key"]
        and chunk_results[i - 1]["last_key"] not in chunk_results[i]["all_keys"]
    )

    tps = total_words / total_elapsed if total_elapsed > 0 else 0.0

    # Node density: sum of per-chunk unique counts divided by total words.
    # This mirrors the calibrator formula (avg_unique / avg_eff_tokens) so that
    # confidence ratios are directly comparable against the sweet-spot baseline.
    per_chunk_unique_sum = sum(m["unique_nodes"] for m in chunk_results)
    node_density = per_chunk_unique_sum / total_words if total_words > 0 else 0.0

    return {
        "filename":           filepath.name,
        "total_words":        total_words,
        "chunk_size":         _WATCH_CHUNK_SIZE,
        "total_unique_nodes": len(all_unique_keys),  # global dedup count (for display)
        "node_density":       round(node_density, 6),
        "stitch_failures":    stitch_failures,
        "tps":                round(tps, 1),
        "num_chunks":         len(chunks),
        "elapsed":            round(total_elapsed, 4),
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def _append_audit_log(
    result: Dict[str, Any],
    baseline_density: float,
    confidence_ratio: float,
    status: str,
) -> None:
    """Append one row to master_audit_log.csv, writing the header if needed."""
    _AUDIT_CSV.parent.mkdir(exist_ok=True)
    write_header = not _AUDIT_CSV.exists()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    row = {
        "timestamp":          ts,
        "filename":           result["filename"],
        "total_words":        result["total_words"],
        "chunk_size":         result["chunk_size"],
        "total_unique_nodes": result["total_unique_nodes"],
        "node_density":       result["node_density"],
        "stitch_failures":    result["stitch_failures"],
        "tps":                result["tps"],
        "baseline_density":   round(baseline_density, 6),
        "confidence_ratio":   confidence_ratio,
        "status":             status,
    }

    with open(_AUDIT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_AUDIT_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Status Report
# ---------------------------------------------------------------------------

_BADGE = {
    "GREEN":  "  GREEN  ",
    "YELLOW": " YELLOW  ",
    "RED":    "   RED   ",
}


def _print_status_report(
    result: Dict[str, Any],
    status: str,
    confidence_ratio: float,
    baseline_density: float,
) -> None:
    color_key = status.split(":")[0].strip()
    badge = _BADGE.get(color_key, f" {color_key} ")
    threshold_note = (
        f"BELOW {_RED_THRESHOLD:.0%} - flagged"
        if confidence_ratio < _RED_THRESHOLD
        else f"above {_RED_THRESHOLD:.0%} threshold"
    )
    stitch_note = (
        "LOGIC BREAK DETECTED" if result["stitch_failures"] > 0 else "OK"
    )

    div = "=" * 65
    print(f"\n{div}")
    print(f"  STATUS REPORT  [{badge}]  {status}")
    print(div)
    print(f"  File             : {result['filename']}")
    print(f"  Words / Chunks   : {result['total_words']:>10,}  /  {result['num_chunks']} chunk(s)")
    print(f"  Unique Nodes     : {result['total_unique_nodes']:>10}")
    print(f"  Node Density     : {result['node_density']:>12.6f}  nodes/word  (this file)")
    print(f"  Baseline Density : {baseline_density:>12.6f}  nodes/word  (sweet-spot)")
    print(f"  Confidence Ratio : {confidence_ratio:>12.4f}  ({threshold_note})")
    print(f"  Stitch Failures  : {result['stitch_failures']:>10}  ({stitch_note})")
    print(f"  TPS              : {result['tps']:>12,.1f}  tokens/sec")
    print(f"  Elapsed          : {result['elapsed']:>12.4f}s")
    print(f"  Audit log        : {_AUDIT_CSV}")
    print(div)


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

def watchdog(
    input_dir: str = "data/input",
    poll_interval: int = 10,
    batch_csv: str = "outputs/batch_report.csv",
    dashboard_png: str = "outputs/performance_benchmark.png",
) -> None:
    """
    Poll *input_dir* every *poll_interval* seconds for new .txt files.

    For each new file:
      - Extract at the 5k-token threshold.
      - Score confidence against the sweet-spot baseline.
      - Regenerate the analytics dashboard PNG.
      - Append a row to master_audit_log.csv.
      - Print a Status Report.

    Runs until interrupted with Ctrl-C.
    """
    from src.visualizer import generate_dashboard

    watch_path = Path(input_dir)

    # Safety guard: refuse to watch excluded directories (outputs/, data/analytics/)
    resolved = watch_path.resolve()
    for _excl in _EXCLUDED_WATCH_DIRS:
        excl_resolved = Path(_excl).resolve()
        if resolved == excl_resolved or str(resolved).startswith(str(excl_resolved) + "\\") or str(resolved).startswith(str(excl_resolved) + "/"):
            raise ValueError(
                f"[monitor] SAFETY BLOCK: '{input_dir}' resolves to a protected directory "
                f"('{_excl}' is excluded from watchdog monitoring)."
            )

    watch_path.mkdir(parents=True, exist_ok=True)

    # Seed the seen-set with files already present so we only react to new arrivals
    seen: Set[str] = {p.name for p in watch_path.glob("*.txt")}

    print(f"\n[monitor] Watchdog started")
    print(f"[monitor] Polling    : {watch_path.resolve()}  (every {poll_interval}s)")
    print(f"[monitor] Chunk size : {_WATCH_CHUNK_SIZE:,} tokens")
    print(f"[monitor] Audit log  : {_AUDIT_CSV.resolve()}")
    print(f"[monitor] Pre-seeded : {len(seen)} existing file(s) ignored")
    print(f"[monitor] Press Ctrl-C to stop.\n")

    while True:
        try:
            # Reload baseline on every poll so a fresh calibration run is picked up
            baseline = _load_baseline()
            baseline_density = (
                baseline["node_recovery_rate"] if baseline else 0.0
            )
            baseline_label = (
                f"{baseline['doc_name']} @ {baseline['chunk_size_tokens']} tokens  "
                f"density={baseline_density:.6f}"
                if baseline
                else "NONE — run src.calibrator first"
            )

            current = {p.name for p in watch_path.glob("*.txt")}
            new_files = sorted(current - seen)

            if not new_files:
                ts = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[monitor] {ts}  waiting for new files ...  "
                    f"(baseline: {baseline_label})"
                )
            else:
                for fname in new_files:
                    fpath = watch_path / fname
                    print(f"\n[monitor] New file detected : {fname}")
                    print(f"[monitor] Baseline          : {baseline_label}")

                    # 1. Extract
                    result = _extract_file(fpath)

                    # 2. Confidence scoring
                    status, confidence_ratio = success_predictor(
                        result["node_density"],
                        result["stitch_failures"],
                        baseline_density,
                    )

                    # 3. Update dashboard
                    if Path(batch_csv).exists():
                        try:
                            generate_dashboard(batch_csv, dashboard_png)
                            print(f"[monitor] Dashboard updated : {dashboard_png}")
                        except Exception as exc:
                            print(f"[monitor] Dashboard skipped : {exc}")
                    else:
                        print(
                            f"[monitor] Dashboard skipped : {batch_csv} not found "
                            f"(run src.calibrator first)"
                        )

                    # 4. Audit log
                    _append_audit_log(
                        result, baseline_density, confidence_ratio, status
                    )

                    # 5. Status report
                    _print_status_report(
                        result, status, confidence_ratio, baseline_density
                    )

                    seen.add(fname)

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\n[monitor] Watchdog stopped.")
            break


if __name__ == "__main__":
    watchdog()
