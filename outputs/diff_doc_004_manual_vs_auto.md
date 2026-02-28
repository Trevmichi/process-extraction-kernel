# Diff: doc_004_manual vs doc_004_auto

- A: `outputs/ap_doc_004.json`
- B: `outputs/ap_doc_004_auto.json`

## Summary

- Nodes: A=11  B=10  (+0 / -1)
- Edges: A=11  B=9  (+4 / -6)
- Unknowns: A=3  B=5  (+2 / -0)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- task:EXECUTE_PAYMENT

### Edges added in B
- gw:IF_CONDITION ->|condition_true| task:REQUEST_CLARIFICATION
- gw:IF_CONDITION ->|condition_true| task:ROUTE_FOR_REVIEW
- gw:IF_CONDITION ->|condition_true| task:UPDATE_RECORD
- task:SCHEDULE_PAYMENT -> end:end

### Edges removed in B
- gw:IF_CONDITION ->|missing| task:REQUEST_CLARIFICATION
- gw:IF_CONDITION ->|not_missing| task:ROUTE_FOR_REVIEW
- task:EXECUTE_PAYMENT -> end:end
- task:REQUEST_CLARIFICATION -> task:UPDATE_RECORD
- task:SCHEDULE_PAYMENT -> task:EXECUTE_PAYMENT
- task:UPDATE_RECORD -> task:ROUTE_FOR_REVIEW

### Unknowns added in B
- Decision detected but branches not fully modeled: 'If approved' — what are the explicit outcomes and next steps?
- Decision detected but branches not fully modeled: 'If the invoice is missing a GL account code' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- (none)
