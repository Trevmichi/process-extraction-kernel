from dataclasses import dataclass
from typing import Any


@dataclass
class OracleResult:
    case_id: str
    label: str
    source: str  # "gold" or "runtime"
    metadata: dict[str, Any]
