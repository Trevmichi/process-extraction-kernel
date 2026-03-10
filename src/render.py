import json
from dataclasses import asdict
from .models import ProcessDoc

def to_json(process: ProcessDoc) -> str:
    """

    Args:
      process: ProcessDoc:
      process: ProcessDoc: 

    Returns:

    """
    obj = {
        "meta": process.meta,
        "actors": process.actors,
        "artifacts": process.artifacts,
        "nodes": [asdict(n) for n in process.nodes],
        "edges": [asdict(e) for e in process.edges],
        "rules": process.rules,
        "unknowns": process.unknowns,
        "assumptions": process.assumptions
    }
    return json.dumps(obj, indent=2)
