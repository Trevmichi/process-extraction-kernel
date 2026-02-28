"""
database.py
SQLite-backed metrics store for process extraction runs.
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path("data/analytics/metrics.db")


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT    NOT NULL,
                file_id          TEXT    NOT NULL,
                model_name       TEXT    NOT NULL,
                node_count       INTEGER NOT NULL,
                edge_count       INTEGER NOT NULL,
                unknown_count    INTEGER NOT NULL,
                complexity_score REAL    NOT NULL,
                success_rate     REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calibration_results (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp             TEXT    NOT NULL,
                doc_name              TEXT    NOT NULL,
                chunk_size_tokens     INTEGER NOT NULL,
                num_chunks            INTEGER NOT NULL,
                avg_effective_tokens  REAL    NOT NULL,
                avg_unique_nodes      REAL    NOT NULL,
                avg_unknown_count     REAL    NOT NULL,
                avg_broken_edges      REAL    NOT NULL,
                node_recovery_rate    REAL    NOT NULL,
                logic_integrity       INTEGER NOT NULL,
                latency_per_1k_tokens REAL    NOT NULL,
                info_density          REAL    NOT NULL,
                sweet_spot            INTEGER NOT NULL DEFAULT 0,
                stitch_failures       INTEGER NOT NULL DEFAULT 0,
                vram_delta_mb         INTEGER,
                tps                   REAL    NOT NULL DEFAULT 0.0
            )
        """)
        # Migrate older schema that lacks the three new columns
        for _col in [
            "stitch_failures INTEGER NOT NULL DEFAULT 0",
            "vram_delta_mb INTEGER",
            "tps REAL NOT NULL DEFAULT 0.0",
        ]:
            try:
                conn.execute(f"ALTER TABLE calibration_results ADD COLUMN {_col}")
            except Exception:
                pass  # column already exists


def log_extraction(
    file_id: str,
    model_name: str,
    node_count: int,
    edge_count: int,
    unknown_count: int,
    char_count: int,
) -> None:
    """Insert one extraction metrics row."""
    init_db()
    complexity_score = char_count / node_count if node_count > 0 else 0.0
    success_rate = node_count / (node_count + unknown_count) if (node_count + unknown_count) > 0 else 0.0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO extraction_logs
                (timestamp, file_id, model_name, node_count, edge_count,
                 unknown_count, complexity_score, success_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, file_id, model_name, node_count, edge_count,
             unknown_count, complexity_score, success_rate),
        )


def log_calibration_result(
    doc_name: str,
    chunk_size_tokens: int,
    num_chunks: int,
    avg_effective_tokens: float,
    avg_unique_nodes: float,
    avg_unknown_count: float,
    avg_broken_edges: float,
    node_recovery_rate: float,
    logic_integrity: int,
    latency_per_1k_tokens: float,
    info_density: float,
    sweet_spot: bool = False,
    stitch_failures: int = 0,
    vram_delta_mb: int | None = None,
    tps: float = 0.0,
) -> None:
    """Insert one calibration stress-test row."""
    init_db()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO calibration_results
                (timestamp, doc_name, chunk_size_tokens, num_chunks,
                 avg_effective_tokens, avg_unique_nodes, avg_unknown_count,
                 avg_broken_edges, node_recovery_rate, logic_integrity,
                 latency_per_1k_tokens, info_density, sweet_spot,
                 stitch_failures, vram_delta_mb, tps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, doc_name, chunk_size_tokens, num_chunks,
             avg_effective_tokens, avg_unique_nodes, avg_unknown_count,
             avg_broken_edges, node_recovery_rate, logic_integrity,
             latency_per_1k_tokens, info_density, int(sweet_spot),
             stitch_failures, vram_delta_mb, tps),
        )


def get_performance_trends() -> None:
    """Print a summary table of the last 5 extraction log entries."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, file_id, model_name,
                   node_count, edge_count, unknown_count,
                   ROUND(complexity_score, 2)  AS complexity_score,
                   ROUND(success_rate,     4)  AS success_rate
            FROM extraction_logs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    col = "{:<26} {:<24} {:<12} {:>6} {:>6} {:>9} {:>11} {:>8}"
    header = col.format(
        "timestamp", "file_id", "model",
        "nodes", "edges", "unknowns", "complexity", "success",
    )
    print("  " + header)
    print("  " + "-" * len(header))
    if not rows:
        print("  (no metrics recorded yet)")
        return
    for r in rows:
        print("  " + col.format(
            r["timestamp"], r["file_id"], r["model_name"],
            r["node_count"], r["edge_count"], r["unknown_count"],
            f"{r['complexity_score']:.2f}", f"{r['success_rate']:.4f}",
        ))
