from dataclasses import dataclass, field
from typing import Any, Literal

CandidateType = Literal[
    "threshold",
    "conjunction",
    "vendor_cohort",
    "evidence_presence",
    "exception_trigger",
]


@dataclass
class CandidateInvariant:
    candidate_id: str
    candidate_type: CandidateType
    description: str
    predicate_repr: str
    support_count: int
    contradiction_count: int
    gold_agreement: float
    runtime_agreement: float
    uncertainty_score: float
    affected_examples: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)
