"""
calibrator.py
High-capacity batch stress-test tool.

Measures metrics at each chunk-size threshold:
  - Node Recovery Rate   : unique_nodes / chunk_words  (nodes per word)
  - Logic Integrity      : count of broken/unlinked edges  (0 = perfect)
  - Processing Latency   : elapsed_sec / (chunk_words / 1000)  (sec per 1k tokens)
  - Stitch Failures      : inter-chunk handoffs where the last intent of chunk[i]
                           does not appear in chunk[i+1]  (0 = perfect continuity)
  - TPS                  : tokens (words) processed per second

Tokens are approximated as whitespace-delimited words (1 word ~= 1 token).

Run directly:
    py -m src.calibrator
or import and call test_batch_efficiency().
"""
from __future__ import annotations

import csv
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Stress-test thresholds (approximate token / word counts)
TEST_THRESHOLDS = [5000, 7500, 10000, 15000]

# Structural bookmarks — excluded from meaningful-node counts
_SKIP_KEYS = {"event:start", "end:end"}

# Multiplier at which unknowns are considered "spiking" (breaking point)
_SPIKE_FACTOR = 2.0

# Threshold for the Victory Lap summary
_VICTORY_LAP_THRESHOLD = 15000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _words_to_chunks(words: List[str], chunk_size: int) -> List[str]:
    """Split a word list into text chunks of at most *chunk_size* words.

    Args:
      words: List[str]:
      chunk_size: int:
      words: List[str]: 
      chunk_size: int: 

    Returns:

    """
    chunks = []
    for i in range(0, max(1, len(words)), max(1, chunk_size)):
        chunk = " ".join(words[i: i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks if chunks else [" ".join(words)]


def _get_vram_mb() -> Optional[int]:
    """ """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def _run_extraction(text: str, source_id: str) -> Dict[str, Any]:
    """Run heuristic extraction on *text* and return a metrics dict:
        unique_nodes   - count of distinct canonical keys (excl. start/end)
        unknown_count  - number of open-question unknowns in the ProcessDoc
        broken_edges   - edges whose frm or to references a missing node id
        total_nodes    - raw node count (incl. start/end)
        all_keys       - set of all meaningful canonical keys in this chunk
        last_key       - last meaningful canonical key in node-list order

    Args:
      text: str:
      source_id: str:
      text: str: 
      source_id: str: 

    Returns:

    """
    from src.heuristic import heuristic_extract_ap

    proc = heuristic_extract_ap(
        text, source_id=source_id, process_id=f"calib_{source_id}"
    )
    node_ids = {n.id for n in proc.nodes}
    unique_keys = (
        {n.meta.get("canonical_key", "") for n in proc.nodes} - _SKIP_KEYS - {""}
    )
    broken = sum(
        1 for e in proc.edges
        if e.frm not in node_ids or e.to not in node_ids
    )

    # Ordered meaningful keys for stitch-failure analysis
    ordered_keys = [
        n.meta.get("canonical_key", "")
        for n in proc.nodes
        if n.meta.get("canonical_key", "") not in _SKIP_KEYS | {""}
    ]
    last_key = ordered_keys[-1] if ordered_keys else ""

    return {
        "unique_nodes": len(unique_keys),
        "total_nodes": len(proc.nodes),
        "unknown_count": len(proc.unknowns),
        "broken_edges": broken,
        "all_keys": unique_keys,
        "last_key": last_key,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def test_batch_efficiency(
    input_path: str = "data/ap_heavy_stress.txt",
    output_csv: str = "outputs/batch_report.csv",
) -> str:
    """Run the high-capacity stress test across TEST_THRESHOLDS chunk sizes,
    persist results to the DB, write *output_csv*, and print a summary.
    
    Returns the path to the written CSV.

    Args:
      input_path: str:  (Default value = "data/ap_heavy_stress.txt")
      output_csv: str:  (Default value = "outputs/batch_report.csv")
      input_path: str:  (Default value = "data/ap_heavy_stress.txt")
      output_csv: str:  (Default value = "outputs/batch_report.csv")

    Returns:

    """
    from src.database import log_calibration_result

    Path("outputs").mkdir(exist_ok=True)

    text = Path(input_path).read_text(encoding="utf-8")
    words = text.split()
    total_words = len(words)
    doc_name = Path(input_path).stem

    vram_probe = _get_vram_mb()
    print(f"\n[stress-test] source     : {input_path}")
    print(f"[stress-test] words      : {total_words}  (~{total_words} tokens)")
    print(f"[stress-test] thresholds : {TEST_THRESHOLDS}")
    print(f"[stress-test] VRAM probe : "
          f"{'nvidia-smi OK — ' + str(vram_probe) + ' MiB in use' if vram_probe is not None else 'not available (CPU-only run)'}\n")

    rows: List[Dict[str, Any]] = []

    for chunk_size in TEST_THRESHOLDS:
        chunks = _words_to_chunks(words, chunk_size)
        num_chunks = len(chunks)

        totals: Dict[str, float] = {
            "unique_nodes": 0.0,
            "unknown_count": 0.0,
            "broken_edges": 0.0,
            "elapsed": 0.0,
            "chunk_words": 0.0,
        }

        chunk_results: List[Dict[str, Any]] = []
        vram_before = _get_vram_mb()

        for idx, chunk in enumerate(chunks):
            cw = len(chunk.split())
            t0 = time.perf_counter()
            m = _run_extraction(chunk, source_id=f"{doc_name}_{chunk_size}_{idx}")
            elapsed = time.perf_counter() - t0

            totals["unique_nodes"] += m["unique_nodes"]
            totals["unknown_count"] += m["unknown_count"]
            totals["broken_edges"] += m["broken_edges"]
            totals["elapsed"] += elapsed
            totals["chunk_words"] += cw
            chunk_results.append(m)

            tps_chunk = cw / elapsed if elapsed > 0 else 0.0
            print(
                f"  threshold={chunk_size:>6}  chunk {idx+1}/{num_chunks}"
                f"  words={cw:>6}"
                f"  unique_nodes={m['unique_nodes']:>3}"
                f"  unknowns={m['unknown_count']:>3}"
                f"  broken_edges={m['broken_edges']:>2}"
                f"  {elapsed:.4f}s  TPS={tps_chunk:>10,.0f}"
            )

        vram_after = _get_vram_mb()
        vram_delta: Optional[int] = None
        if vram_before is not None and vram_after is not None:
            vram_delta = vram_after - vram_before

        # --- Stitch failure analysis ---
        # A stitch failure: the last meaningful canonical intent of chunk[i]
        # does not appear anywhere in chunk[i+1], meaning the process thread
        # is dropped at the boundary.
        stitch_failures = 0
        for i in range(1, len(chunk_results)):
            prev_last = chunk_results[i - 1]["last_key"]
            curr_keys = chunk_results[i]["all_keys"]
            if prev_last and prev_last not in curr_keys:
                stitch_failures += 1

        avg_eff_tokens = totals["chunk_words"] / num_chunks
        avg_unique     = totals["unique_nodes"] / num_chunks
        avg_unknown    = totals["unknown_count"] / num_chunks
        avg_broken     = totals["broken_edges"] / num_chunks
        avg_elapsed    = totals["elapsed"] / num_chunks

        # --- Three success metrics ---
        # 1. Node Recovery Rate: unique nodes found per word in the chunk
        node_recovery_rate = avg_unique / avg_eff_tokens if avg_eff_tokens > 0 else 0.0

        # 2. Logic Integrity: total broken edges across all chunks (0 = perfect)
        logic_integrity = int(totals["broken_edges"])

        # 3. Processing Latency: seconds per 1,000 tokens
        latency_per_1k = avg_elapsed / (avg_eff_tokens / 1000) if avg_eff_tokens > 0 else 0.0

        # Information Density (kept for continuity)
        info_density = avg_unique / avg_elapsed if avg_elapsed > 0 else 0.0

        # TPS: total words processed / total elapsed for this threshold
        tps_total = totals["chunk_words"] / totals["elapsed"] if totals["elapsed"] > 0 else 0.0

        rows.append({
            "chunk_size_tokens":     chunk_size,
            "doc_total_words":       total_words,
            "num_chunks":            num_chunks,
            "avg_effective_tokens":  round(avg_eff_tokens, 1),
            "avg_unique_nodes":      round(avg_unique, 2),
            "avg_unknown_count":     round(avg_unknown, 2),
            "avg_broken_edges":      round(avg_broken, 2),
            "node_recovery_rate":    round(node_recovery_rate, 6),
            "logic_integrity":       logic_integrity,
            "latency_per_1k_tokens": round(latency_per_1k, 4),
            "info_density":          round(info_density, 4),
            "stitch_failures":       stitch_failures,
            "vram_delta_mb":         vram_delta if vram_delta is not None else -1,
            "tps":                   round(tps_total, 1),
            "sweet_spot":            "",
        })

    # --- Sweet spot: highest info_density ---
    best = max(rows, key=lambda r: r["info_density"])
    best["sweet_spot"] = "YES"

    # --- Breaking point: first threshold where unknowns spike >= SPIKE_FACTOR x prev ---
    breaking_point: int | None = None
    for i in range(1, len(rows)):
        prev_unk = rows[i - 1]["avg_unknown_count"]
        curr_unk = rows[i]["avg_unknown_count"]
        if prev_unk > 0 and curr_unk >= prev_unk * _SPIKE_FACTOR:
            breaking_point = rows[i]["chunk_size_tokens"]
            break

    # --- Persist to DB ---
    for r in rows:
        log_calibration_result(
            doc_name=doc_name,
            chunk_size_tokens=r["chunk_size_tokens"],
            num_chunks=r["num_chunks"],
            avg_effective_tokens=r["avg_effective_tokens"],
            avg_unique_nodes=r["avg_unique_nodes"],
            avg_unknown_count=r["avg_unknown_count"],
            avg_broken_edges=r["avg_broken_edges"],
            node_recovery_rate=r["node_recovery_rate"],
            logic_integrity=r["logic_integrity"],
            latency_per_1k_tokens=r["latency_per_1k_tokens"],
            info_density=r["info_density"],
            sweet_spot=(r["sweet_spot"] == "YES"),
            stitch_failures=r["stitch_failures"],
            vram_delta_mb=r["vram_delta_mb"] if r["vram_delta_mb"] != -1 else None,
            tps=r["tps"],
        )

    # --- Write CSV ---
    fieldnames = [
        "chunk_size_tokens", "doc_total_words", "num_chunks",
        "avg_effective_tokens", "avg_unique_nodes", "avg_unknown_count",
        "avg_broken_edges", "node_recovery_rate", "logic_integrity",
        "latency_per_1k_tokens", "info_density",
        "stitch_failures", "vram_delta_mb", "tps", "sweet_spot",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # --- Stress Test Summary ---
    _print_summary(rows, breaking_point, output_csv)

    # --- Victory Lap (15k threshold) ---
    victory_row = next(
        (r for r in rows if r["chunk_size_tokens"] == _VICTORY_LAP_THRESHOLD), None
    )
    if victory_row:
        _print_victory_lap(victory_row)

    return output_csv


def _print_summary(
    rows: List[Dict[str, Any]],
    breaking_point: int | None,
    csv_path: str,
) -> None:
    """

    Args:
      rows: List[Dict[str:
      Any]]: 
      breaking_point: int | None:
      csv_path: str:
      rows: List[Dict[str: 
      breaking_point: int | None: 
      csv_path: str: 

    Returns:

    """
    hdr = (
        f"  {'threshold':>10} {'chunks':>7} {'eff_tok':>8}"
        f" {'nodes':>7} {'unknowns':>9} {'broken':>7}"
        f" {'recovery':>10} {'lat/1k':>8} {'density':>10}"
        f" {'stitchFail':>11} {'TPS':>9} {'flag':>12}"
    )
    div = "  " + "-" * (len(hdr) - 2)

    print(f"\n{'='*80}")
    print("  STRESS TEST SUMMARY")
    print('='*80)
    print(hdr)
    print(div)

    for r in rows:
        flag = ""
        if r["sweet_spot"] == "YES":
            flag = "SWEET SPOT"
        if breaking_point and r["chunk_size_tokens"] == breaking_point:
            flag = "BREAKING PT"
        print(
            f"  {r['chunk_size_tokens']:>10} {r['num_chunks']:>7} {r['avg_effective_tokens']:>8.1f}"
            f" {r['avg_unique_nodes']:>7.2f} {r['avg_unknown_count']:>9.2f} {r['avg_broken_edges']:>7.2f}"
            f" {r['node_recovery_rate']:>10.6f} {r['latency_per_1k_tokens']:>8.4f}"
            f" {r['info_density']:>10.4f}"
            f" {r['stitch_failures']:>11} {r['tps']:>9,.0f} {flag:>12}"
        )

    print(div)
    if breaking_point:
        print(f"\n  !! BREAKING POINT detected at {breaking_point} tokens "
              f"(unknowns spiked >={_SPIKE_FACTOR:.0f}x)")
    else:
        print("\n  OK  No breaking point detected across tested thresholds.")

    print(f"\n  Results saved to  : {csv_path}")
    print(f"  DB table          : calibration_results (outputs/metrics.db)")
    print('='*80)


def _print_victory_lap(r: Dict[str, Any]) -> None:
    """Print the Victory Lap summary for the 15k-token threshold run.

    Args:
      r: Dict[str:
      Any]: 
      r: Dict[str: 

    Returns:

    """
    tps         = r["tps"]
    nodes       = r["avg_unique_nodes"]
    recovery    = r["node_recovery_rate"]
    stitches    = r["stitch_failures"]
    num_chunks  = r["num_chunks"]
    total_words = r["doc_total_words"]
    vram_val    = r["vram_delta_mb"]
    vram_str    = f"{vram_val:+d} MiB delta" if vram_val != -1 else "N/A (CPU-only run)"

    stitch_max   = max(num_chunks - 1, 1)
    stitch_pct   = 100.0 * (1 - stitches / stitch_max) if stitch_max > 0 else 100.0
    stitch_label = "PERFECT" if stitches == 0 else f"{stitches} failure(s)"

    print(f"\n{'='*70}")
    print(f"  VICTORY LAP  --  {_VICTORY_LAP_THRESHOLD:,}-TOKEN THRESHOLD")
    print(f"{'='*70}")
    print(f"  Document size        : {total_words:>10,} words  (~{total_words:,} tokens)")
    print(f"  Chunks produced      : {num_chunks:>10}")
    print()
    print(f"  Tokens/sec (TPS)     : {tps:>12,.1f}  tokens per second")
    print(f"  Node Recovery Ratio  : {recovery:>12.6f}  nodes per word")
    print(f"  Avg Unique Nodes     : {nodes:>12.2f}  per chunk")
    print(f"  Stitch Continuity    : {stitch_label:<20}  "
          f"({stitch_pct:.0f}% of {stitch_max} handoff(s) intact)")
    print(f"  VRAM Usage           : {vram_str}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    test_batch_efficiency()
