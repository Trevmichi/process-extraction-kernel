"""
unmodeled.py
Append-only JSONL logger for unmodeled routing events.

When the router encounters a NO_ROUTE or AMBIGUOUS_ROUTE situation,
it calls ``record_event()`` to persist structural metadata for later
analysis.  Raw invoice text is **never** logged (privacy).
"""
from __future__ import annotations

import json
from pathlib import Path


_DEFAULT_PATH = "outputs/unmodeled_logic.jsonl"


def record_event(event: dict, path: str = _DEFAULT_PATH) -> None:
    """Append *event* as a single JSON line to the JSONL file at *path*.
    
    Creates parent directories if they do not exist.  The caller is
    responsible for populating the event dict — this function only
    serialises and appends.

    Args:
      event: dict: 
      path: str:  (Default value = _DEFAULT_PATH)

    Returns:

    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
