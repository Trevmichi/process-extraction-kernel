# Diff: doc_001_manual vs doc_001_auto

- A: `outputs/ap_doc_001.json`
- B: `outputs/ap_doc_001_auto.json`

## Summary

- Nodes: A=11  B=10  (+2 / -2)
- Edges: A=11  B=11  (+7 / -6)
- Unknowns: A=5  B=4  (+1 / -2)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- gw:IF_CONDITION
- task:ROUTE_FOR_REVIEW

### Nodes removed in B
- gw:MATCH_3_WAY
- task:RECEIVE_MESSAGE

### Edges added in B
- event:start -> task:ENTER_RECORD
- gw:IF_CONDITION ->|true| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount<=thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|true| task:ROUTE_FOR_REVIEW
- task:ROUTE_FOR_REVIEW -> task:SCHEDULE_PAYMENT
- task:VALIDATE_FIELDS -> gw:IF_CONDITION

### Edges removed in B
- event:start -> task:RECEIVE_MESSAGE
- gw:MATCH_3_WAY ->|match| gw:THRESHOLD_AMOUNT
- gw:THRESHOLD_AMOUNT ->|amount<=5000| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>5000| task:APPROVE
- task:RECEIVE_MESSAGE -> task:ENTER_RECORD
- task:VALIDATE_FIELDS -> gw:MATCH_3_WAY

### Unknowns added in B
- If the invoice matches the PO and goods receipt (match), what are the explicit outcomes and next steps?

### Unknowns removed in B
- If 3-way match fails (no_match), what is the process (hold, vendor contact, reject, override)?
- What is the match tolerance for price/quantity variances in matching (and who sets it)?
