"""
benchmarker.py
Multi-Threshold Benchmark Suite (Grid Search).

Runs the process extraction pipeline across TEST_CHUNKS chunk sizes against
data/ap_heavy_stress.txt (the 17k-word reference document).

For each chunk size the suite:
  1. Splits the document into non-overlapping chunks.
  2. Runs heuristic extraction on each chunk SEQUENTIALLY.
  3. Records: Latency (sec), Node Count, Unknown Count, and
     Success Probability  SP = nodes / (nodes + unknowns).
  4. Saves the result to the hyperparameter_results DB table.
  5. Calls gc.collect() + waits 15 s to clear RTX 5070 VRAM
     before the next chunk size begins (skipped after the last run).

After all runs the suite:
  - Generates outputs/performance_curve.png via src.visualizer.
  - Prints an Optimization Recommendation for the chunk size with the best SP.

Run:
    py -m src.benchmarker
or import and call run_benchmark().
"""
from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Grid-search parameters
# ---------------------------------------------------------------------------

TEST_CHUNKS: List[int] = [1250]  # Gold Standard baseline

_INPUT_PATH  = "data/ap_heavy_stress.txt"
_CURVE_PNG   = "outputs/performance_curve.png"
_VRAM_PAUSE  = 15         # seconds between runs — gives RTX 5070 fans time to
                          # spin down and VRAM a hard reset before next chunk size
_PEAK_ZONE   = 0.90       # SP ≥ 90 % of max → "Peak Accuracy Zone"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vram_mb() -> Optional[int]:
    """Return current GPU VRAM used in MiB via nvidia-smi, or None."""
    import subprocess
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return int(r.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def _fmt_chunks(chunk_size: int) -> str:
    """Format a chunk size as e.g. '5k' or '3.5k'."""
    v = chunk_size / 1000
    return f"{v:g}k"


# ---------------------------------------------------------------------------
# Single chunk-size benchmark
# ---------------------------------------------------------------------------

def _run_one_chunk_size(
    words: List[str],
    chunk_size: int,
    doc_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Process the full document word list at *chunk_size* words per chunk.

    Returns a result dict with all recorded metrics, or None if a result for
    this (doc_name, chunk_size) already exists in the DB (resume / skip).
    """
    from src.database import get_hyperparameter_result

    # ------------------------------------------------------------------
    # Resume check — skip if this chunk size was already benchmarked.
    # Two cases:
    #   • DB row present  → run completed cleanly; skip and load cached result.
    #   • No DB row       → run either never started or crashed before
    #                       log_hyperparameter_result() was called; re-run
    #                       all sub-chunks from scratch for this chunk size.
    # ------------------------------------------------------------------
    existing = get_hyperparameter_result(doc_name, chunk_size)
    if existing is not None:
        print(f"[SKIP] Already benchmarked chunk_size={_fmt_chunks(chunk_size)}"
              f"  (SP={existing['success_probability']:.6f} from previous run)")
        return None

    from src.calibrator import _words_to_chunks, _run_extraction
    from src.llm_classifier import get_heatmap_log, clear_heatmap_log

    chunks = _words_to_chunks(words, chunk_size)
    num_chunks = len(chunks)
    total_nodes    = 0
    total_unknowns = 0
    heatmap_entries: List[Dict[str, Any]] = []
    density_entries: List[Dict[str, Any]] = []

    t0 = time.perf_counter()

    for idx, chunk in enumerate(chunks):
        chunk_words = len(chunk.split())
        print(
            f"  [{_fmt_chunks(chunk_size)}]  chunk {idx + 1:>2}/{num_chunks}"
            f"  words={chunk_words:>6}",
            end="  ",
        )
        clear_heatmap_log()
        m = _run_extraction(chunk, source_id=f"bench_{doc_name}_{chunk_size}_{idx}")
        total_nodes    += m["unique_nodes"]
        total_unknowns += m["unknown_count"]

        position_pct = round((idx + 0.5) / num_chunks, 4)

        # Collect depth from any self-healing that fired during this chunk
        log_entries = get_heatmap_log()
        chunk_depth = max((e["depth"] for e in log_entries), default=0)
        heatmap_entries.append({
            "chunk_size":   chunk_size,
            "position_pct": position_pct,
            "depth":        chunk_depth,
            "text_preview": chunk[:30],
        })

        # Record per-chunk node density for logic density profile
        density_entries.append({
            "chunk_size":    chunk_size,
            "position_pct":  position_pct,
            "node_count":    m["unique_nodes"],
            "unknown_count": m["unknown_count"],
            "chunk_words":   chunk_words,
        })

        print(
            f"nodes={m['unique_nodes']:>3}  "
            f"unknowns={m['unknown_count']:>3}  "
            f"depth={chunk_depth}"
        )

    latency_sec = time.perf_counter() - t0
    sp = (
        total_nodes / (total_nodes + total_unknowns)
        if (total_nodes + total_unknowns) > 0 else 0.0
    )
    max_recursion_depth = max((e["depth"] for e in heatmap_entries), default=0)

    return {
        "chunk_size_tokens":    chunk_size,
        "num_chunks":           num_chunks,
        "total_node_count":     total_nodes,
        "total_unknown_count":  total_unknowns,
        "latency_sec":          round(latency_sec, 4),
        "success_probability":  round(sp, 6),
        "max_recursion_depth":  max_recursion_depth,
        "heatmap_data":         heatmap_entries,
        "density_data":         density_entries,
    }


# ---------------------------------------------------------------------------
# Results table printer
# ---------------------------------------------------------------------------

def _print_results_table(results: List[Dict[str, Any]]) -> None:
    hdr = (
        f"  {'Chunk':>6}  {'Chunks':>6}  {'Nodes':>7}  "
        f"{'Unknowns':>9}  {'Latency':>9}  {'SP':>10}  {'Zone':>16}"
    )
    div = "  " + "-" * (len(hdr) - 2)

    max_sp      = max(r["success_probability"] for r in results)
    peak_thresh = _PEAK_ZONE * max_sp

    print(f"\n{'=' * 70}")
    print("  GRID SEARCH RESULTS")
    print("=" * 70)
    print(hdr)
    print(div)

    for r in results:
        in_zone = r["success_probability"] >= peak_thresh
        zone_tag = "PEAK ACCURACY ZONE" if in_zone else ""
        best_tag = " *** BEST ***" if r["success_probability"] == max_sp else ""
        print(
            f"  {_fmt_chunks(r['chunk_size_tokens']):>6}"
            f"  {r['num_chunks']:>6}"
            f"  {r['total_node_count']:>7}"
            f"  {r['total_unknown_count']:>9}"
            f"  {r['latency_sec']:>8.2f}s"
            f"  {r['success_probability']:>10.6f}"
            f"  {zone_tag}{best_tag}"
        )

    print(div)


# ---------------------------------------------------------------------------
# Optimization Recommendation
# ---------------------------------------------------------------------------

def _print_recommendation(results: List[Dict[str, Any]]) -> None:
    best = max(results, key=lambda r: r["success_probability"])
    max_sp = best["success_probability"]
    peak_thresh = _PEAK_ZONE * max_sp
    zone_members = [r for r in results if r["success_probability"] >= peak_thresh]
    zone_sizes   = [r["chunk_size_tokens"] for r in zone_members]

    # Among peak-zone members, prefer the one with the lowest latency
    fastest_in_zone = min(zone_members, key=lambda r: r["latency_sec"])

    print(f"\n{'=' * 70}")
    print("  OPTIMIZATION RECOMMENDATION")
    print("=" * 70)
    print(f"  Highest SP           : {max_sp:.6f}  "
          f"@ chunk size {_fmt_chunks(best['chunk_size_tokens'])}")
    print(f"  Peak Accuracy Zone   : {[_fmt_chunks(s) for s in zone_sizes]}  "
          f"(SP ≥ {_PEAK_ZONE:.0%} of max)")
    print()
    print(f"  RECOMMENDATION:")
    print(f"    Use chunk size  {_fmt_chunks(fastest_in_zone['chunk_size_tokens'])}  "
          f"for production.")
    print(f"    It sits inside the Peak Accuracy Zone "
          f"(SP = {fastest_in_zone['success_probability']:.6f})")
    print(f"    and is the fastest among zone members "
          f"({fastest_in_zone['latency_sec']:.2f}s total latency).")
    if fastest_in_zone["chunk_size_tokens"] != best["chunk_size_tokens"]:
        print(f"    Peak SP is at {_fmt_chunks(best['chunk_size_tokens'])} "
              f"but that chunk size is "
              f"{best['latency_sec']:.2f}s — "
              f"{best['latency_sec'] - fastest_in_zone['latency_sec']:.2f}s slower.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_benchmark(
    input_path: str = _INPUT_PATH,
    out_png: str = _CURVE_PNG,
) -> List[Dict[str, Any]]:
    """
    Run the full grid search across TEST_CHUNKS and return the results list.

    Side effects:
      - Persists every run to DB table hyperparameter_results.
      - Saves outputs/performance_curve.png.
      - Prints a results table and an Optimization Recommendation.
    """
    from src.database import log_hyperparameter_result
    from src.visualizer import generate_performance_curve

    src_path = Path(input_path)
    if not src_path.exists():
        raise FileNotFoundError(
            f"[benchmarker] Input file not found: {src_path.resolve()}"
        )

    text  = src_path.read_text(encoding="utf-8", errors="replace")
    words = text.split()
    total_words = len(words)
    doc_name = src_path.stem

    vram_start = _get_vram_mb()

    print(f"\n{'=' * 70}")
    print("  BENCHMARKER — Multi-Threshold Grid Search")
    print("=" * 70)
    print(f"  Source file  : {src_path.resolve()}")
    print(f"  Document     : {total_words:,} words  (~{total_words:,} tokens)")
    print(f"  Chunk sizes  : {TEST_CHUNKS}")
    print(f"  VRAM (start) : "
          f"{str(vram_start) + ' MiB' if vram_start is not None else 'N/A (nvidia-smi not found)'}")
    print(f"  VRAM pause   : {_VRAM_PAUSE}s + gc.collect() between runs")
    print("=" * 70 + "\n")

    results: List[Dict[str, Any]] = []
    all_heatmap_data: List[Dict[str, Any]] = []
    all_density_data: List[Dict[str, Any]] = []

    for run_idx, chunk_size in enumerate(TEST_CHUNKS):
        # ---- VRAM cool-down between runs (not before the first) ----
        if run_idx > 0:
            print(
                f"\n[benchmarker] VRAM cool-down: gc.collect() + {_VRAM_PAUSE}s pause ...",
                flush=True,
            )
            gc.collect()
            time.sleep(_VRAM_PAUSE)

        print(f"\n[benchmarker] Run {run_idx + 1}/{len(TEST_CHUNKS)}"
              f"  chunk_size={_fmt_chunks(chunk_size)}")

        result = _run_one_chunk_size(words, chunk_size, doc_name)

        if result is None:
            # Skipped — reload cached row from DB so charts stay complete
            from src.database import get_hyperparameter_result
            cached = get_hyperparameter_result(doc_name, chunk_size)
            if cached is not None:
                results.append(cached)
            continue

        # Accumulate heatmap and density data from this run
        all_heatmap_data.extend(result.pop("heatmap_data", []))
        all_density_data.extend(result.pop("density_data", []))

        results.append(result)

        # ---- Persist to DB ----
        log_hyperparameter_result(
            doc_name=doc_name,
            chunk_size_tokens=result["chunk_size_tokens"],
            num_chunks=result["num_chunks"],
            total_node_count=result["total_node_count"],
            total_unknown_count=result["total_unknown_count"],
            latency_sec=result["latency_sec"],
            success_probability=result["success_probability"],
            max_recursion_depth=result["max_recursion_depth"],
        )

        print(
            f"  => SP={result['success_probability']:.6f}  "
            f"nodes={result['total_node_count']}  "
            f"unknowns={result['total_unknown_count']}  "
            f"latency={result['latency_sec']:.2f}s  "
            f"max_depth={result['max_recursion_depth']}  [saved to DB]"
        )

    # ---- Summary table ----
    _print_results_table(results)

    # ---- Performance Curve chart ----
    Path("outputs").mkdir(exist_ok=True)
    generate_performance_curve(results, out_png)

    # ---- Optimization Recommendation ----
    _print_recommendation(results)

    # ---- Schema Discovery Report ----
    from src.visualizer import generate_schema_report
    schema = generate_schema_report()
    if schema["total_misses"] > 0:
        print(
            f"\n[benchmarker] Found {schema['total_misses']} non-canonical action(s) "
            f"across {schema['unique_actions']} unique type(s). "
            f"See {schema['out_md']}"
        )
    else:
        print("\n[benchmarker] Schema clean — no non-canonical actions detected.")

    # ---- Top-5 Unknown Schema Types (actions + decisions) ----
    import json as _json
    _sugg_path = Path("data/analytics/schema_suggestions.json")
    if _sugg_path.exists() and _sugg_path.stat().st_size > 0:
        _counts: Dict[str, int] = _json.loads(
            _sugg_path.read_text(encoding="utf-8")
        )
        _action_misses   = {k: v for k, v in _counts.items()
                            if not k.startswith("DECISION:")}
        _decision_misses = {k: v for k, v in _counts.items()
                            if k.startswith("DECISION:")}
        if _action_misses or _decision_misses:
            print(f"\n{'=' * 70}")
            print("  TOP UNKNOWN SCHEMA TYPES  (update ontology/aliases as needed)")
            print("=" * 70)
            if _action_misses:
                print("  Actions:")
                for k, v in sorted(
                    _action_misses.items(), key=lambda x: x[1], reverse=True
                )[:5]:
                    print(f"    {k:<35}  ({v}x)")
            if _decision_misses:
                print("  Decisions:")
                for k, v in sorted(
                    _decision_misses.items(), key=lambda x: x[1], reverse=True
                )[:5]:
                    print(f"    {k.removeprefix('DECISION:'):<35}  ({v}x)")
            print("=" * 70)

    # ---- Self-Healing Complexity Heatmap ----
    from src.visualizer import generate_complexity_heatmap
    generate_complexity_heatmap(
        all_heatmap_data,
        out_png="outputs/process_complexity_heatmap.png",
    )

    # ---- Logic Density Profile (1.25k run, total nodes per chunk) ----
    from src.visualizer import generate_logic_density_profile
    density_info = generate_logic_density_profile(
        all_density_data,
        chunk_size=TEST_CHUNKS[0],   # smallest tier = finest resolution
        out_png="outputs/logic_density_profile.png",
    )
    print(
        f"\n[benchmarker] Logic Density Profile generated. "
        f"Peak complexity found at chunk {density_info['peak_chunk_idx']} "
        f"({density_info['peak_total_nodes']} total nodes, "
        f"avg {density_info['avg_total_nodes']:.1f} nodes/chunk)."
    )

    return results


if __name__ == "__main__":
    run_benchmark()
