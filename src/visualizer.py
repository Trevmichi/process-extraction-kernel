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
            xy=(xi, yi), xytext=(0, 10),
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


if __name__ == "__main__":
    generate_dashboard()
