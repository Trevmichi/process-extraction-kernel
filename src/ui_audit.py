"""
ui_audit.py
Pure, defensively-coded parsers for APState audit_log entries.

All functions treat non-dict and non-JSON entries as ignorable.
No function raises on malformed input — they degrade to ``None``
or an empty list.
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Internal: safely parse a log entry
# ---------------------------------------------------------------------------

def _try_parse(entry: Any) -> dict | None:
    """Attempt to parse *entry* into a dict.
    
    Returns ``None`` for non-string / non-dict entries, unparseable JSON,
    or anything that isn't a dict after parsing.

    Args:
      entry: Any:
      entry: Any: 

    Returns:

    """
    if isinstance(entry, dict):
        return entry
    if not isinstance(entry, str):
        return None
    try:
        parsed = json.loads(entry)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_exception_event(audit_log: list) -> dict | None:
    """

    Args:
      audit_log: list:
      audit_log: list: 

    Returns:
      : Scans the log in reverse so the last occurrence wins.

    """
    for entry in reversed(audit_log):
        parsed = _try_parse(entry)
        if parsed is not None and parsed.get("event") == "exception_station":
            return parsed
    return None


def extract_match_event(audit_log: list) -> dict | None:
    """

    Args:
      audit_log: list:
      audit_log: list: 

    Returns:

    """
    for entry in reversed(audit_log):
        parsed = _try_parse(entry)
        if parsed is not None and parsed.get("event") == "match_result_set":
            return parsed
    return None


def extract_router_events(audit_log: list) -> list[dict]:
    """

    Args:
      audit_log: list:
      audit_log: list: 

    Returns:
      : Router events are identified by the presence of a ``"candidates"``
      or ``"matched_targets"`` key, or by ``event`` containing ``"route"``.
      Plain ``"Executed ..."`` strings are also included as best-effort
      route-step markers.

    """
    results: list[dict] = []
    for entry in audit_log:
        parsed = _try_parse(entry)
        if parsed is not None:
            ev = parsed.get("event", "")
            if (
                ev in ("route_decision", "route_record")
                or "candidates" in parsed
                or "matched_targets" in parsed
            ):
                results.append(parsed)
            continue
        # Plain string entries that look like route steps
        if isinstance(entry, str) and entry.startswith("Executed "):
            results.append({"raw": entry})
    return results


def extract_verifier_event(audit_log: list) -> dict | None:
    """

    Args:
      audit_log: list:
      audit_log: list: 

    Returns:
      : Matches entries whose ``event`` is ``"extraction"`` or ``"verifier"``.

    """
    for entry in reversed(audit_log):
        parsed = _try_parse(entry)
        if parsed is not None and parsed.get("event") in ("extraction", "verifier"):
            return parsed
    return None
