from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal
from .ontology import (
    ActionType, DecisionType, ActorId, ArtifactId,
    VALID_ACTIONS, VALID_DECISIONS, VALID_ACTORS, VALID_ARTIFACTS,
)

NodeKind = Literal["event", "task", "gateway", "end"]

@dataclass
class Evidence:
    source_id: str
    span: str

@dataclass
class Action:
    type: ActionType
    actor_id: ActorId | str
    artifact_id: ArtifactId | str
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in VALID_ACTIONS:
            import json as _json
            import warnings
            from pathlib import Path as _Path

            # Terminal log — visible in benchmarker output
            print(f"[SCHEMA MISS] AI used '{self.type}'")
            warnings.warn(
                f"[ACTION GUARD] Unknown action type {self.type!r} — "
                f"coercing to 'UNKNOWN_ACTION' to prevent benchmark crash.",
                stacklevel=2,
            )

            # Persist frequency counter so generate_schema_report() can analyse it
            _suggestions = _Path("data/analytics/schema_suggestions.json")
            try:
                _suggestions.parent.mkdir(parents=True, exist_ok=True)
                _counts: Dict[str, int] = (
                    _json.loads(_suggestions.read_text(encoding="utf-8"))
                    if _suggestions.exists() and _suggestions.stat().st_size > 0
                    else {}
                )
                _counts[self.type] = _counts.get(self.type, 0) + 1
                _suggestions.write_text(
                    _json.dumps(_counts, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except Exception as _exc:
                print(f"[SCHEMA MISS] Could not update schema_suggestions.json: {_exc}")

            self.extra["original_type"] = self.type
            self.type = "UNKNOWN_ACTION"
        if self.actor_id not in VALID_ACTORS:
            self.extra["raw_actor_id"] = self.actor_id
            self.actor_id = "sys_erp"
        if self.artifact_id not in VALID_ARTIFACTS:
            self.extra["raw_artifact_id"] = self.artifact_id
            self.artifact_id = ""

@dataclass
class Decision:
    type: DecisionType
    inputs: List[str] = field(default_factory=list)
    expression: Optional[str] = None

    def __post_init__(self) -> None:
        if self.type not in VALID_DECISIONS:
            import json as _json
            import warnings
            from pathlib import Path as _Path

            # Terminal log — visible in benchmarker output
            print(f"[SCHEMA MISS] AI used Decision type '{self.type}'")
            warnings.warn(
                f"[DECISION GUARD] Unknown decision type {self.type!r} — "
                f"coercing to 'IF_CONDITION' to prevent benchmark crash.",
                stacklevel=2,
            )

            # Persist frequency counter — keyed with "DECISION:" prefix so
            # generate_schema_report() can distinguish decision misses from action misses
            _suggestions = _Path("data/analytics/schema_suggestions.json")
            try:
                _suggestions.parent.mkdir(parents=True, exist_ok=True)
                _counts: Dict[str, int] = (
                    _json.loads(_suggestions.read_text(encoding="utf-8"))
                    if _suggestions.exists() and _suggestions.stat().st_size > 0
                    else {}
                )
                _miss_key = f"DECISION:{self.type}"
                _counts[_miss_key] = _counts.get(_miss_key, 0) + 1
                _suggestions.write_text(
                    _json.dumps(_counts, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except Exception as _exc:
                print(f"[SCHEMA MISS] Could not update schema_suggestions.json: {_exc}")

            self.type = "IF_CONDITION"

@dataclass
class Node:
    """Represents a process node, with optional metadata for extensions and annotations.

    The ``meta`` field can be used to attach arbitrary, implementation-specific
    information to a node (for example, UI hints, tags, or integration data).
    """
    id: str
    kind: NodeKind
    name: str = ""
    action: Optional[Action] = None
    decision: Optional[Decision] = None
    evidence: List[Evidence] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Edge:
    frm: str
    to: str
    condition: Optional[str] = None

@dataclass
class ProcessDoc:
    meta: Dict[str, Any]
    actors: List[Dict[str, Any]]
    artifacts: List[Dict[str, Any]]
    nodes: List[Node]
    edges: List[Edge]
    rules: List[Dict[str, Any]] = field(default_factory=list)
    unknowns: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
