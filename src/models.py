from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

NodeKind = Literal["event", "task", "gateway", "end"]

@dataclass
class Evidence:
    source_id: str
    span: str

@dataclass
class Action:
    type: str
    actor_id: str
    artifact_id: str
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Decision:
    type: str
    inputs: List[str] = field(default_factory=list)
    expression: Optional[str] = None

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
