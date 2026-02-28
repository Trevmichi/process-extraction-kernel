# Diff: doc_003_manual vs doc_003_auto

- A: `outputs/ap_doc_003.json`
- B: `outputs/ap_doc_003_auto.json`

## Summary

- Nodes: A=9  B=6  (+0 / -2)
- Edges: A=8  B=5  (+2 / -5)
- Unknowns: A=7  B=5  (+0 / -2)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- task:RECEIVE_MESSAGE
- task:UPDATE_STATUS

### Edges added in B
- gw:VARIANCE_ABOVE_TOLERANCE ->|variance_above_tolerance| task:REQUEST_CLARIFICATION
- task:REQUEST_CLARIFICATION -> task:UPDATE_RECORD

### Edges removed in B
- gw:VARIANCE_ABOVE_TOLERANCE ->|above_tolerance| task:UPDATE_STATUS
- task:MATCH_3_WAY -> end:end
- task:RECEIVE_MESSAGE -> task:UPDATE_RECORD
- task:REQUEST_CLARIFICATION -> task:RECEIVE_MESSAGE
- task:UPDATE_STATUS -> task:REQUEST_CLARIFICATION

### Unknowns added in B
- (none)

### Unknowns removed in B
- If variance is within tolerance, what is the next step (auto-approve, manager review)?
- What are the tolerance thresholds for quantity/price variance?
