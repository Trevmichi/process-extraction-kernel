"""
visualizer.py
Analytics dashboard for process extraction calibration results.

Reads outputs/batch_report.csv, adds a Success Probability score,
rewrites the CSV, and saves a dual-axis performance chart:
  - Y1 (left, line)  : TPS — tokens processed per second
  - Y2 (right, bars) : Avg Unknown Count per chunk

Success Probability = avg_unique_nodes / doc_total_words
  (fraction of total document words that resolved to a canonical node)

Run directly:
    py -m src.visualizer
or import and call generate_dashboard().
"""
from __future__ import annotations

import csv
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Success Probability
# ---------------------------------------------------------------------------

def _add_success_probability(rows: List[Dict[str, Any]]) -> None:
    """
    Compute success_probability in-place for each row.

    success_probability = avg_unique_nodes / doc_total_words
    Represents the fraction of total document words that resolved
    to a distinct canonical process node.
    """
    for r in rows:
        avg_unique = float(r["avg_unique_nodes"])
        doc_words  = float(r["doc_total_words"])
        r["success_probability"] = round(avg_unique / doc_words, 6) if doc_words > 0 else 0.0


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def _build_chart(
    rows: List[Dict[str, Any]],
    out_png: str,
) -> None:
    thresholds = [int(r["chunk_size_tokens"]) for r in rows]
    tps        = [float(r["tps"]) for r in rows]
    unknowns   = [float(r["avg_unknown_count"]) for r in rows]
    success_p  = [float(r["success_probability"]) for r in rows]
    sweet_idx  = next((i for i, r in enumerate(rows) if r.get("sweet_spot") == "YES"), None)

    x_pos  = np.arange(len(thresholds))
    labels = [f"{t // 1000}k" for t in thresholds]

    # ------------------------------------------------------------------ figure
    fig, ax1 = plt.subplots(figsize=(11, 6))
    fig.patch.set_facecolor("#F0F4F8")
    ax1.set_facecolor("#F8FAFC")

    # ------------------------------------------------------------------ Y2: bars (unknowns)
    ax2 = ax1.twinx()
    bar_width = 0.45
    bar_colors = ["#FDBA74" if i != sweet_idx else "#86EFAC" for i in range(len(rows))]
    bars = ax2.bar(
        x_pos, unknowns, width=bar_width,
        color=bar_colors, alpha=0.75, label="Avg Unknowns / chunk", zorder=2,
        edgecolor="#9CA3AF", linewidth=0.8,
    )
    ax2.set_ylabel("Avg Unknown Count per Chunk", color="#C2410C", fontsize=11)
    ax2.tick_params(axis="y", labelcolor="#C2410C")
    ax2.set_ylim(0, max(unknowns) * 1.35)

    # ------------------------------------------------------------------ Y1: TPS line
    line_tps = ax1.plot(
        x_pos, tps,
        color="#2563EB", marker="o", linewidth=2.5,
        markersize=9, zorder=4, label="TPS (Throughput)",
    )
    ax1.set_ylabel("Tokens per Second (TPS)", color="#1D4ED8", fontsize=11)
    ax1.tick_params(axis="y", labelcolor="#1D4ED8")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.set_ylim(0, max(tps) * 1.30)

    # ------------------------------------------------------------------ Sweet spot marker
    if sweet_idx is not None:
        ax1.axvline(
            x=sweet_idx, color="#16A34A", linestyle="--",
            linewidth=1.8, alpha=0.8, zorder=1,
        )
        ax1.annotate(
            "Sweet Spot",
            xy=(sweet_idx, tps[sweet_idx]),
            xytext=(sweet_idx + 0.12, tps[sweet_idx] * 1.12),
            color="#16A34A", fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#16A34A", lw=1.2),
        )

    # ------------------------------------------------------------------ TPS labels on line
    for xi, yi in zip(x_pos, tps):
        ax1.annotate(
            f"{yi:,.0f}",
            xy=(float(xi), yi), xytext=(0, 10),
            textcoords="offset points",
            ha="center", fontsize=8, color="#1E3A8A", fontweight="bold",
        )

    # ------------------------------------------------------------------ Success probability on bars
    for bar, sp in zip(bars, success_p):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(unknowns) * 0.015,
            f"SP={sp:.5f}",
            ha="center", va="bottom", fontsize=7.5, color="#6D28D9",
        )

    # ------------------------------------------------------------------ X axis
    ax1.set_xlabel("Chunk Size Threshold (tokens)", fontsize=11)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(labels, fontsize=12)
    ax1.set_xlim(-0.6, len(x_pos) - 0.4)
    ax1.grid(axis="y", linestyle="--", alpha=0.35, zorder=0)

    # ------------------------------------------------------------------ Legend
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        handles1 + handles2, labels1 + labels2,
        loc="upper left", fontsize=9, framealpha=0.85,
    )

    # ------------------------------------------------------------------ Titles
    fig.suptitle(
        "Process Extraction — Performance Benchmark",
        fontsize=14, fontweight="bold", y=0.99,
    )
    ax1.set_title(
        "TPS (line, left axis) vs Avg Unknown Count (bars, right axis) by Chunk Size",
        fontsize=9, color="#4B5563", pad=8,
    )

    plt.tight_layout()
    Path(out_png).parent.mkdir(exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_dashboard(
    csv_path: str = "outputs/batch_report.csv",
    out_png: str = "outputs/performance_benchmark.png",
) -> str:
    """
    Load calibration CSV, append success_probability, save the chart, and
    rewrite the CSV.  Returns the path to the saved PNG.
    """
    # --- Load CSV ---
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, Any]] = list(reader)

    if not rows:
        raise ValueError(f"No data found in {csv_path}")

    # --- Compute and attach success_probability ---
    _add_success_probability(rows)

    # --- Rewrite CSV with new column ---
    existing_fields = list(rows[0].keys())
    # Insert success_probability before sweet_spot
    if "success_probability" not in existing_fields:
        idx = existing_fields.index("sweet_spot")
        existing_fields.insert(idx, "success_probability")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=existing_fields)
        writer.writeheader()
        writer.writerows(rows)

    # --- Build and save chart ---
    _build_chart(rows, out_png)

    print(f"[visualizer] Chart saved  : {out_png}")
    print(f"[visualizer] CSV updated  : {csv_path}  (+success_probability)")
    return out_png


# ---------------------------------------------------------------------------
# Performance Curve — SP vs Chunk Size (benchmarker output)
# ---------------------------------------------------------------------------

def generate_performance_curve(
    results: List[Dict[str, Any]],
    out_png: str = "outputs/performance_curve.png",
    peak_zone_pct: float = 0.90,
) -> str:
    """
    Build a 'Performance Curve' chart: Success Probability vs Chunk Size.

    *results* is the list of result dicts produced by src.benchmarker, each
    containing at minimum:
        chunk_size_tokens   int
        total_node_count    int
        total_unknown_count int
        latency_sec         float
        success_probability float

    The 'Peak Accuracy Zone' is shaded for all chunk sizes whose SP is at
    or above *peak_zone_pct* × the maximum SP observed.

    Returns the path to the saved PNG.
    """
    if not results:
        raise ValueError("generate_performance_curve: results list is empty")

    results_sorted = sorted(results, key=lambda r: r["chunk_size_tokens"])

    chunk_sizes  = [r["chunk_size_tokens"] for r in results_sorted]
    sp_values    = [float(r["success_probability"]) for r in results_sorted]
    node_counts  = [int(r["total_node_count"]) for r in results_sorted]
    latencies    = [float(r["latency_sec"]) for r in results_sorted]

    max_sp       = max(sp_values) if sp_values else 1.0
    peak_thresh  = peak_zone_pct * max_sp
    best_idx     = sp_values.index(max_sp)

    x_pos  = np.arange(len(chunk_sizes))
    labels = [f"{cs / 1000:g}k" for cs in chunk_sizes]

    # ------------------------------------------------------------------ figure
    fig, ax1 = plt.subplots(figsize=(13, 6))
    fig.patch.set_facecolor("#F0F4F8")
    ax1.set_facecolor("#F8FAFC")

    # ------------------------------------------------------------------ Peak Accuracy Zone shading
    in_zone_xs = [xi for xi, sp in zip(x_pos, sp_values) if sp >= peak_thresh]
    if in_zone_xs:
        zone_lo = min(in_zone_xs) - 0.5
        zone_hi = max(in_zone_xs) + 0.5
        ax1.axvspan(
            zone_lo, zone_hi,
            alpha=0.12, color="#16A34A", zorder=0, label="Peak Accuracy Zone",
        )
        ax1.axhline(
            peak_thresh, color="#16A34A", linestyle=":",
            linewidth=1.2, alpha=0.6, zorder=1,
        )
        ax1.annotate(
            f"Peak zone ≥ {peak_zone_pct:.0%} of max SP",
            xy=(zone_lo + 0.05, peak_thresh),
            xytext=(zone_lo + 0.05, peak_thresh + (max_sp * 0.04)),
            fontsize=7.5, color="#15803D",
            arrowprops=dict(arrowstyle="-", color="#15803D", lw=0.8),
        )

    # ------------------------------------------------------------------ Y2: node count bars
    ax2 = ax1.twinx()
    bar_colors = [
        "#86EFAC" if i == best_idx else "#93C5FD"
        for i in range(len(results_sorted))
    ]
    ax2.bar(
        x_pos, node_counts, width=0.5,
        color=bar_colors, alpha=0.55, label="Total Nodes",
        edgecolor="#9CA3AF", linewidth=0.7, zorder=2,
    )
    ax2.set_ylabel("Total Node Count (bars)", color="#6B7280", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#6B7280")
    ax2.set_ylim(0, max(node_counts) * 1.40)

    # ------------------------------------------------------------------ Y1: SP line
    ax1.plot(
        x_pos, sp_values,
        color="#7C3AED", marker="o", linewidth=2.5,
        markersize=8, zorder=4, label="Success Probability (SP)",
    )

    # Peak star marker
    ax1.plot(
        x_pos[best_idx], max_sp,
        marker="*", color="#DC2626", markersize=18,
        zorder=5, label=f"Peak SP = {max_sp:.4f}",
    )
    ax1.annotate(
        f"BEST\n{labels[best_idx]}\nSP={max_sp:.4f}",
        xy=(x_pos[best_idx], max_sp),
        xytext=(x_pos[best_idx] + 0.35, max_sp - (max_sp * 0.08)),
        fontsize=8, color="#DC2626", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#DC2626", lw=1.3),
    )

    # SP value labels on each point
    for xi, sp in zip(x_pos, sp_values):
        ax1.annotate(
            f"{sp:.4f}",
            xy=(float(xi), sp), xytext=(0, 10),
            textcoords="offset points",
            ha="center", fontsize=7.5, color="#4C1D95", fontweight="bold",
        )

    # ------------------------------------------------------------------ Latency labels on bars
    for xi, lat in zip(x_pos, latencies):
        ax2.text(
            float(xi), 0 + max(node_counts) * 0.012,
            f"{lat:.1f}s",
            ha="center", va="bottom", fontsize=7, color="#374151",
            rotation=90,
        )

    # ------------------------------------------------------------------ axes / labels
    ax1.set_ylabel("Success Probability  (SP = nodes / nodes+unknowns)", color="#4C1D95", fontsize=10)
    ax1.tick_params(axis="y", labelcolor="#4C1D95")
    ax1.set_ylim(0, min(1.0, max_sp * 1.25))
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.3f}"))

    ax1.set_xlabel("Chunk Size (words ≈ tokens)", fontsize=11)
    ax1.set_xticks(x_pos)
    # ha="right" + rotation prevents overlap for decimal labels like "1.25k", "2.05k"
    ax1.set_xticklabels(labels, fontsize=11, rotation=20, ha="right")
    ax1.set_xlim(-0.7, len(x_pos) - 0.3)
    ax1.grid(axis="y", linestyle="--", alpha=0.30, zorder=0)

    # ------------------------------------------------------------------ Legend
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="lower right", fontsize=8.5, framealpha=0.88)

    # ------------------------------------------------------------------ Titles
    fig.suptitle(
        "Chunk-Size Grid Search — Performance Curve",
        fontsize=14, fontweight="bold", y=0.99,
    )
    ax1.set_title(
        "SP (line, left) vs Total Node Count (bars, right) | green shading = Peak Accuracy Zone",
        fontsize=9, color="#4B5563", pad=8,
    )

    plt.tight_layout()
    Path(out_png).parent.mkdir(exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[visualizer] Performance curve saved : {out_png}")
    return out_png


# ---------------------------------------------------------------------------
# Self-Healing Complexity Heatmap
# ---------------------------------------------------------------------------

def generate_complexity_heatmap(
    heatmap_data: List[Dict[str, Any]],
    out_png: str = "outputs/process_complexity_heatmap.png",
) -> str:
    """
    Plot a 'Self-Healing Heatmap' showing where recursive self-healing fired
    across the document, broken down by chunk size.

    *heatmap_data* is a list of per-chunk entries, each containing:
        chunk_size   int    — chunk size for this run
        position_pct float  — centre of the chunk in the document (0.0 – 1.0)
        depth        int    — max recursion depth reached (0 = no self-healing)
        text_preview str    — first 30 chars of the chunk text

    One horizontal row is drawn per unique chunk size (sorted ascending).
    Each chunk is a coloured bar-segment:
        Depth 0  → green  (#86EFAC)  — clean
        Depth 1  → yellow (#FDE68A)  — one split needed
        Depth 2  → orange (#FB923C)  — two splits needed
        Depth 3+ → red    (#EF4444)  — severe struggle

    Hot Zones (depth > 0) are labelled "D{n}" above the bar.

    Returns the path to the saved PNG.
    """
    from collections import defaultdict
    from matplotlib.patches import Patch

    Path(out_png).parent.mkdir(exist_ok=True)

    # ---- graceful empty case ----
    if not heatmap_data:
        fig, ax = plt.subplots(figsize=(13, 2))
        fig.patch.set_facecolor("#F0F4F8")
        ax.text(0.5, 0.5, "No heatmap data collected.",
                ha="center", va="center", fontsize=12, color="#6B7280")
        ax.axis("off")
        plt.tight_layout()
        fig.savefig(out_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[visualizer] Complexity heatmap saved : {out_png}  (no data)")
        return out_png

    # ---- group by chunk size ----
    by_size: dict = defaultdict(list)
    for entry in heatmap_data:
        by_size[entry["chunk_size"]].append(entry)

    chunk_sizes = sorted(by_size.keys())
    n_rows      = len(chunk_sizes)

    _DEPTH_COLORS = {
        0: "#86EFAC",   # green
        1: "#FDE68A",   # yellow
        2: "#FB923C",   # orange
        3: "#EF4444",   # red
    }

    def _color(d: int) -> str:
        return _DEPTH_COLORS.get(min(d, 3), "#EF4444")

    # ---- figure: one subplot row per chunk size ----
    row_h   = 1.3
    fig_h   = max(3.5, n_rows * row_h + 2.0)
    fig, axes = plt.subplots(n_rows, 1, figsize=(14, fig_h))
    if n_rows == 1:
        axes = [axes]
    fig.patch.set_facecolor("#F0F4F8")

    hot_zone_count = 0

    for ax, chunk_size in zip(axes, chunk_sizes):
        entries = sorted(by_size[chunk_size], key=lambda e: e["position_pct"])
        n       = len(entries)
        ax.set_facecolor("#F8FAFC")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 1)
        ax.set_yticks([])

        # Y-axis label shows chunk size
        label_str = f"{chunk_size / 1000:g}k"
        ax.set_ylabel(
            label_str, fontsize=9, rotation=0,
            va="center", ha="right", labelpad=30,
        )

        bar_y = 0.15
        bar_h = 0.65

        for i, entry in enumerate(entries):
            x_lo = (i / n) * 100
            x_hi = ((i + 1) / n) * 100
            w    = x_hi - x_lo

            ax.broken_barh(
                [(x_lo, w)], (bar_y, bar_h),
                facecolors=_color(entry["depth"]),
                edgecolors="#9CA3AF", linewidth=0.4,
            )

            # Label Hot Zones (depth > 0) above the segment
            if entry["depth"] > 0:
                ax.text(
                    x_lo + w / 2, bar_y + bar_h + 0.04,
                    f"D{entry['depth']}",
                    ha="center", va="bottom",
                    fontsize=6.5, color="#7F1D1D", fontweight="bold",
                )
                hot_zone_count += 1

        # X-axis ticks only on the bottom row
        if chunk_size == chunk_sizes[-1]:
            ax.set_xlabel("Document Progress (%)", fontsize=10)
            ax.set_xticks([0, 25, 50, 75, 100])
            ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=9)
        else:
            ax.set_xticks([])

    # ---- "no hot zones" annotation if everything is clean ----
    if hot_zone_count == 0:
        axes[0].text(
            50, 0.88, "No Hot Zones detected — all chunks resolved at Depth 0",
            ha="center", va="top", fontsize=8.5, color="#15803D",
            fontstyle="italic",
        )

    # ---- shared legend (top row) ----
    legend_handles = [
        Patch(facecolor=_DEPTH_COLORS[0], edgecolor="#9CA3AF", label="Depth 0 — clean"),
        Patch(facecolor=_DEPTH_COLORS[1], edgecolor="#9CA3AF", label="Depth 1 — 1 split"),
        Patch(facecolor=_DEPTH_COLORS[2], edgecolor="#9CA3AF", label="Depth 2 — 2 splits"),
        Patch(facecolor=_DEPTH_COLORS[3], edgecolor="#9CA3AF", label="Depth 3+ — severe"),
    ]
    axes[0].legend(
        handles=legend_handles, loc="upper right",
        fontsize=7.5, framealpha=0.92, ncol=4,
    )

    # ---- titles ----
    fig.suptitle(
        "Self-Healing Heatmap — Document Complexity by Position",
        fontsize=13, fontweight="bold",
    )
    axes[0].set_title(
        "Color = max recursion depth per chunk  |  Y rows = chunk size  "
        "|  Hot Zones (D1+) labelled",
        fontsize=8.5, color="#4B5563", pad=6,
    )

    plt.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(
        f"[visualizer] Complexity heatmap saved : {out_png}  "
        f"({hot_zone_count} hot zone(s) across {n_rows} chunk size(s))"
    )
    return out_png


# ---------------------------------------------------------------------------
# Logic Density Profile
# ---------------------------------------------------------------------------

_HIGH_DENSITY_THRESHOLD = 15.0  # nodes per 1k words


def generate_logic_density_chart(
    density_data: List[Dict[str, Any]],
    out_png: str = "outputs/logic_density_comparison.png",
) -> Dict[str, Any]:
    """
    Plot a 'Logic Density Profile' showing nodes-per-1k-words across the
    document, with one line per chunk size.

    *density_data* is a list of per-chunk dicts, each containing:
        chunk_size   int    — chunk size for this run
        position_pct float  — centre of chunk in document (0.0 – 1.0)
        node_count   int    — canonical nodes extracted from this chunk
        chunk_words  int    — word count of this chunk

    Each unique chunk size is drawn as a separate line.  Regions where
    nodes-per-1k-words exceeds _HIGH_DENSITY_THRESHOLD (15) are overlaid
    with a translucent red fill_between band.

    Returns a dict:
        {"out_png": str, "peak_pct": float, "peak_nodes_per_1k": float}
    where peak_pct is the document position (0–100%) of the highest density
    point across all chunk sizes.
    """
    from collections import defaultdict

    Path(out_png).parent.mkdir(exist_ok=True)

    # ---- graceful empty case ----
    if not density_data:
        fig, ax = plt.subplots(figsize=(13, 4))
        fig.patch.set_facecolor("#F0F4F8")
        ax.text(0.5, 0.5, "No density data collected.",
                ha="center", va="center", fontsize=12, color="#6B7280",
                transform=ax.transAxes)
        ax.axis("off")
        plt.tight_layout()
        fig.savefig(out_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[visualizer] Logic density chart saved : {out_png}  (no data)")
        return {"out_png": out_png, "peak_pct": 0.0, "peak_nodes_per_1k": 0.0}

    # ---- group and compute density per chunk ----
    by_size: dict = defaultdict(list)
    for entry in density_data:
        npk = (entry["node_count"] / entry["chunk_words"] * 1000.0
               if entry["chunk_words"] > 0 else 0.0)
        by_size[entry["chunk_size"]].append({
            "position_pct": entry["position_pct"],
            "nodes_per_1k": npk,
        })

    chunk_sizes = sorted(by_size.keys())

    # ---- find global peak across all chunk sizes ----
    global_peak_npk  = 0.0
    global_peak_pos  = 0.0
    for entries in by_size.values():
        for e in entries:
            if e["nodes_per_1k"] > global_peak_npk:
                global_peak_npk = e["nodes_per_1k"]
                global_peak_pos = e["position_pct"]

    # ---- palette: one colour per chunk size ----
    _PALETTE = ["#7C3AED", "#2563EB", "#059669", "#D97706", "#DC2626"]
    colour_map = {cs: _PALETTE[i % len(_PALETTE)] for i, cs in enumerate(chunk_sizes)}

    # ---- figure ----
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#F0F4F8")
    ax.set_facecolor("#F8FAFC")

    for chunk_size in chunk_sizes:
        entries = sorted(by_size[chunk_size], key=lambda e: e["position_pct"])
        xs = [e["position_pct"] * 100 for e in entries]
        ys = [e["nodes_per_1k"] for e in entries]
        col = colour_map[chunk_size]
        label = f"{chunk_size / 1000:g}k chunks"

        ax.plot(xs, ys, color=col, marker="o", markersize=5,
                linewidth=1.8, label=label, zorder=3)
        ax.fill_between(xs, ys, alpha=0.08, color=col, zorder=2)

        # ---- red high-complexity overlay ----
        ax.fill_between(
            xs, ys,
            where=[y > _HIGH_DENSITY_THRESHOLD for y in ys],
            alpha=0.25, color="#EF4444", zorder=4,
            interpolate=True,
        )

    # ---- threshold line ----
    ax.axhline(
        _HIGH_DENSITY_THRESHOLD,
        color="#EF4444", linestyle="--", linewidth=1.2,
        alpha=0.7, zorder=1,
        label=f"High Complexity threshold ({_HIGH_DENSITY_THRESHOLD:.0f} nodes / 1k words)",
    )

    # ---- peak annotation ----
    if global_peak_npk > 0:
        peak_x = global_peak_pos * 100
        ax.annotate(
            f"Peak\n{global_peak_npk:.1f} n/1k\n@ {peak_x:.0f}%",
            xy=(peak_x, global_peak_npk),
            xytext=(peak_x + 4, global_peak_npk + global_peak_npk * 0.10),
            fontsize=7.5, color="#991B1B", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#991B1B", lw=1.2),
        )

    # ---- axes ----
    ax.set_xlabel("Document Progress (%)", fontsize=11)
    ax.set_ylabel("Nodes per 1k Words", fontsize=11, color="#1E3A8A")
    ax.tick_params(axis="y", labelcolor="#1E3A8A")
    ax.set_xlim(0, 100)
    y_max = max(global_peak_npk, _HIGH_DENSITY_THRESHOLD) * 1.30
    ax.set_ylim(0, y_max)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}"))
    ax.grid(axis="y", linestyle="--", alpha=0.30, zorder=0)
    ax.grid(axis="x", linestyle=":", alpha=0.20, zorder=0)

    # ---- legend ----
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.90)

    # ---- titles ----
    fig.suptitle(
        "Logic Density Profile — Nodes per 1k Words Across Document",
        fontsize=13, fontweight="bold", y=0.99,
    )
    ax.set_title(
        "Each line = one chunk size | Red fill = High Complexity zone (> 15 nodes / 1k words)",
        fontsize=8.5, color="#4B5563", pad=6,
    )

    plt.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    peak_pct_out = round(global_peak_pos * 100, 1)
    print(
        f"[visualizer] Logic density chart saved : {out_png}  "
        f"(peak {global_peak_npk:.1f} nodes/1k @ {peak_pct_out:.1f}%)"
    )
    return {
        "out_png": out_png,
        "peak_pct": peak_pct_out,
        "peak_nodes_per_1k": round(global_peak_npk, 2),
    }


# ---------------------------------------------------------------------------
# Logic Density Profile — single chunk-size, total nodes per chunk
# ---------------------------------------------------------------------------

def generate_logic_density_profile(
    density_data: List[Dict[str, Any]],
    chunk_size: int = 1250,
    out_png: str = "outputs/logic_density_profile.png",
) -> Dict[str, Any]:
    """
    Plot a single-run 'Logic Density Profile' for the given *chunk_size*.

    *density_data* is the list of per-chunk dicts collected by the benchmarker,
    each containing:
        chunk_size    int    — chunk size this entry belongs to
        position_pct  float  — centre of chunk in document (0.0 – 1.0)
        node_count    int    — canonical nodes extracted from this chunk
        unknown_count int    — unknown/unclassified nodes
        chunk_words   int    — word count of this chunk

    Y-axis: Total Nodes per Chunk  (node_count + unknown_count)
    X-axis: Chunk Index (document progress)

    Decorations:
      - Area fill under the line
      - Horizontal dashed line at the average total-node density
      - Red dot on the peak chunk

    Falls back to the smallest available chunk size if *chunk_size* is not
    present in the data.

    Returns a dict:
        {"out_png": str, "peak_chunk_idx": int, "peak_total_nodes": int,
         "avg_total_nodes": float, "chunk_size_used": int}
    """
    Path(out_png).parent.mkdir(exist_ok=True)

    # ---- graceful empty case ----
    if not density_data:
        fig, ax = plt.subplots(figsize=(13, 4))
        fig.patch.set_facecolor("#F0F4F8")
        ax.text(0.5, 0.5, "No density data collected.",
                ha="center", va="center", fontsize=12, color="#6B7280",
                transform=ax.transAxes)
        ax.axis("off")
        plt.tight_layout()
        fig.savefig(out_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[visualizer] Logic density profile saved : {out_png}  (no data)")
        return {"out_png": out_png, "peak_chunk_idx": 0, "peak_total_nodes": 0,
                "avg_total_nodes": 0.0, "chunk_size_used": chunk_size}

    # ---- select chunk size (fall back to smallest available) ----
    available = sorted({e["chunk_size"] for e in density_data})
    chunk_size_used = chunk_size if chunk_size in available else available[0]
    if chunk_size_used != chunk_size:
        print(f"[visualizer] chunk_size={chunk_size} not found; "
              f"falling back to {chunk_size_used}")

    entries = sorted(
        [e for e in density_data if e["chunk_size"] == chunk_size_used],
        key=lambda e: e["position_pct"],
    )

    xs = list(range(len(entries)))
    ys = [e["node_count"] + e.get("unknown_count", 0) for e in entries]

    if not ys:
        fig, ax = plt.subplots(figsize=(13, 4))
        fig.patch.set_facecolor("#F0F4F8")
        ax.text(0.5, 0.5, f"No chunks found for chunk_size={chunk_size_used}.",
                ha="center", va="center", fontsize=12, color="#6B7280",
                transform=ax.transAxes)
        ax.axis("off")
        plt.tight_layout()
        fig.savefig(out_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return {"out_png": out_png, "peak_chunk_idx": 0, "peak_total_nodes": 0,
                "avg_total_nodes": 0.0, "chunk_size_used": chunk_size_used}

    avg_nodes    = sum(ys) / len(ys)
    peak_idx     = ys.index(max(ys))
    peak_nodes   = ys[peak_idx]

    # ---- figure ----
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#F0F4F8")
    ax.set_facecolor("#F8FAFC")

    # Line + area fill
    ax.plot(xs, ys, color="#2563EB", marker="o", markersize=5,
            linewidth=2.0, zorder=3, label="Total Nodes per Chunk")
    ax.fill_between(xs, ys, alpha=0.15, color="#2563EB", zorder=2)

    # Average density line
    ax.axhline(
        avg_nodes,
        color="#059669", linestyle="--", linewidth=1.4,
        alpha=0.85, zorder=1,
        label=f"Avg Node Density  ({avg_nodes:.1f} nodes/chunk)",
    )
    ax.annotate(
        f"Avg = {avg_nodes:.1f}",
        xy=(len(xs) - 1, avg_nodes),
        xytext=(-5, 6), textcoords="offset points",
        ha="right", fontsize=8, color="#065F46", fontweight="bold",
    )

    # Peak marker
    ax.plot(peak_idx, peak_nodes, marker="*", color="#DC2626",
            markersize=14, zorder=5, label=f"Peak  ({peak_nodes} nodes @ chunk {peak_idx})")
    ax.annotate(
        f"Peak\n{peak_nodes} nodes\nchunk {peak_idx}",
        xy=(peak_idx, peak_nodes),
        xytext=(peak_idx + max(1, len(xs) * 0.04),
                peak_nodes + peak_nodes * 0.08),
        fontsize=7.5, color="#991B1B", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#991B1B", lw=1.2),
    )

    # ---- axes ----
    ax.set_xlabel(f"Chunk Index  (chunk size = {chunk_size_used / 1000:g}k words)",
                  fontsize=11)
    ax.set_ylabel("Total Nodes per Chunk  (valid + unknowns)", fontsize=11,
                  color="#1E3A8A")
    ax.tick_params(axis="y", labelcolor="#1E3A8A")
    ax.set_xlim(-0.5, len(xs) - 0.5)
    ax.set_ylim(0, max(peak_nodes, avg_nodes) * 1.30)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.grid(axis="y", linestyle="--", alpha=0.30, zorder=0)
    ax.grid(axis="x", linestyle=":", alpha=0.20, zorder=0)

    # ---- legend ----
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.90)

    # ---- titles ----
    label_str = f"{chunk_size_used / 1000:g}k"
    fig.suptitle(
        f"Logic Density Profile — {label_str} Chunk Size  "
        f"({len(xs)} chunks across document)",
        fontsize=13, fontweight="bold", y=0.99,
    )
    ax.set_title(
        "Y = valid nodes + unknowns per chunk  |  green dashed = average density  "
        "|  red star = peak",
        fontsize=8.5, color="#4B5563", pad=6,
    )

    plt.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(
        f"[visualizer] Logic density profile saved : {out_png}  "
        f"(chunk_size={label_str}, peak={peak_nodes} nodes @ chunk {peak_idx}, "
        f"avg={avg_nodes:.1f})"
    )
    return {
        "out_png":          out_png,
        "peak_chunk_idx":   peak_idx,
        "peak_total_nodes": peak_nodes,
        "avg_total_nodes":  round(avg_nodes, 2),
        "chunk_size_used":  chunk_size_used,
    }


# ---------------------------------------------------------------------------
# Schema Discovery Report
# ---------------------------------------------------------------------------

def generate_schema_report(
    json_path: str = "data/analytics/schema_suggestions.json",
    out_md: str = "outputs/schema_suggestions.md",
) -> Dict[str, Any]:
    """
    Load data/analytics/schema_suggestions.json (written by Action.__post_init__)
    and produce a Markdown report at *out_md*.

    Each row shows:
        Suggested Action | Frequency | Recommended Mapping

    Recommended Mapping is derived from ACTION_ALIASES in src.heuristic:
      - If already aliased  → confirms the existing mapping
      - If not aliased       → "Add to ACTION_ALIASES in src/heuristic.py"

    Returns a dict: {"total_misses": int, "unique_actions": int, "out_md": str}
    """
    import json as _json

    Path(out_md).parent.mkdir(exist_ok=True)

    json_file = Path(json_path)
    if not json_file.exists() or json_file.stat().st_size == 0:
        Path(out_md).write_text(
            "# Schema Discovery Report\n\nNo non-canonical actions detected.\n",
            encoding="utf-8",
        )
        print(f"[visualizer] Schema report saved : {out_md}  (no misses)")
        return {"total_misses": 0, "unique_actions": 0, "out_md": out_md}

    counts: Dict[str, int] = _json.loads(json_file.read_text(encoding="utf-8"))
    if not counts:
        Path(out_md).write_text(
            "# Schema Discovery Report\n\nNo non-canonical actions detected.\n",
            encoding="utf-8",
        )
        print(f"[visualizer] Schema report saved : {out_md}  (no misses)")
        return {"total_misses": 0, "unique_actions": 0, "out_md": out_md}

    # Load ACTION_ALIASES for mapping suggestions
    try:
        from src.heuristic import ACTION_ALIASES
    except ImportError:
        ACTION_ALIASES = {}

    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    total_misses  = sum(counts.values())

    lines: List[str] = [
        "# Schema Discovery Report",
        "",
        f"> Total non-canonical action instances recorded: **{total_misses}**  ",
        f"> Unique unknown action types: **{len(counts)}**  ",
        f"> Source: `{json_path}`",
        "",
        "| Suggested Action | Frequency | Recommended Mapping |",
        "|---|---|---|",
    ]

    for action, freq in sorted_counts:
        if action in ACTION_ALIASES:
            mapping = (
                f"Already aliased → `{ACTION_ALIASES[action]}` "
                f"*(confirm entry in `ACTION_ALIASES`)*"
            )
        else:
            mapping = "Add to `ACTION_ALIASES` in `src/heuristic.py`"
        lines.append(f"| `{action}` | {freq} | {mapping} |")

    lines += [
        "",
        "## Next Steps",
        "",
        "For each row above, choose one of:",
        "1. Map to an existing canonical action — add an entry to `ACTION_ALIASES`"
        " in `src/heuristic.py`.",
        "2. Introduce a new canonical action — add to `VALID_ACTIONS` in"
        " `src/ontology.py` and update the system prompt in `src/llm_classifier.py`.",
        "",
        f"*Re-run `py -m src.benchmarker` after updating aliases to validate the fix.*",
    ]

    Path(out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[visualizer] Schema report saved : {out_md}  ({total_misses} miss(es),"
          f" {len(counts)} unique)")
    return {"total_misses": total_misses, "unique_actions": len(counts), "out_md": out_md}


if __name__ == "__main__":
    generate_dashboard()
