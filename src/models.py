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
            raise ValueError(f"Invalid Action.type {self.type!r}; expected one of {sorted(VALID_ACTIONS)}")
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
            raise ValueError(f"Invalid Decision.type {self.type!r}; expected one of {sorted(VALID_DECISIONS)}")

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
