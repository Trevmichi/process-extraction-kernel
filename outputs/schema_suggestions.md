# Schema Discovery Report

> Total non-canonical action instances recorded: **3**  
> Unique unknown action types: **3**  
> Source: `data/analytics/schema_suggestions.json`

| Suggested Action | Frequency | Recommended Mapping |
|---|---|---|
| `RERUN_PROCESS` | 1 | Add to `ACTION_ALIASES` in `src/heuristic.py` |
| `UPDATE` | 1 | Add to `ACTION_ALIASES` in `src/heuristic.py` |
| `true` | 1 | Add to `ACTION_ALIASES` in `src/heuristic.py` |

## Next Steps

For each row above, choose one of:
1. Map to an existing canonical action — add an entry to `ACTION_ALIASES` in `src/heuristic.py`.
2. Introduce a new canonical action — add to `VALID_ACTIONS` in `src/ontology.py` and update the system prompt in `src/llm_classifier.py`.

*Re-run `py -m src.benchmarker` after updating aliases to validate the fix.*
