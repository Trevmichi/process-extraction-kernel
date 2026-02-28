# Diff: doc_003_manual vs doc_003_auto

- A: `outputs/ap_doc_003.json`
- B: `outputs/ap_doc_003_auto.json`

## Summary

- Nodes: A=9  B=7  (+1 / -3)
- Edges: A=8  B=6  (+5 / -7)
- Unknowns: A=7  B=4  (+1 / -4)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- gw:IF_CONDITION

### Nodes removed in B
- gw:VARIANCE_ABOVE_TOLERANCE
- task:REQUEST_CLARIFICATION
- task:UPDATE_STATUS

### Edges added in B
- gw:IF_CONDITION -> task:RECEIVE_MESSAGE
- task:MATCH_3_WAY -> gw:IF_CONDITION
- task:MATCH_3_WAY -> task:UPDATE_RECORD
- task:RECEIVE_MESSAGE -> task:MATCH_3_WAY
- task:UPDATE_RECORD -> end:end

### Edges removed in B
- gw:VARIANCE_ABOVE_TOLERANCE ->|above_tolerance| task:UPDATE_STATUS
- task:MATCH_3_WAY -> end:end
- task:MATCH_3_WAY -> gw:VARIANCE_ABOVE_TOLERANCE
- task:RECEIVE_MESSAGE -> task:UPDATE_RECORD
- task:REQUEST_CLARIFICATION -> task:RECEIVE_MESSAGE
- task:UPDATE_RECORD -> task:MATCH_3_WAY
- task:UPDATE_STATUS -> task:REQUEST_CLARIFICATION

### Unknowns added in B
- Decision detected but branches not fully modeled: 'If there is a quantity mismatch or price variance above the tolerance, the invoice is placed on hold and AP contacts the vendor for clarification.' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- If variance is within tolerance, what happens next (auto-approve, manager review, or pay hold)?
- If variance is within tolerance, what is the next step (auto-approve, manager review)?
- What are the tolerance thresholds for quantity/price variance?
- What is the escalation policy if the vendor does not respond (time limits, reminders, who owns escalation)?
