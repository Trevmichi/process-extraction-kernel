import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

def trace_event(path: str, action_type: str, payload: Dict[str, Any], cost: Optional[Dict[str, Any]] = None) -> None:
    evt = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action_type": action_type,
        "payload": payload,
        "cost": cost or {}
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt) + "\n")
