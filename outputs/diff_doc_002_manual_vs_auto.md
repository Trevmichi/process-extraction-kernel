# Diff: doc_002_manual vs doc_002_auto

- A: `outputs/ap_doc_002.json`
- B: `outputs/ap_doc_002_auto.json`

## Summary

- Nodes: A=12  B=14  (+2 / -1)
- Edges: A=11  B=13  (+8 / -6)
- Unknowns: A=5  B=6  (+3 / -2)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- task:APPROVE
- task:REJECT

### Nodes removed in B
- task:RECEIVE_MESSAGE

### Edges added in B
- event:start -> gw:HAS_PO
- gw:APPROVE_OR_REJECT -> end:end
- gw:APPROVE_OR_REJECT ->|reject| task:REJECT
- gw:HAS_PO -> task:ROUTE_FOR_REVIEW
- task:APPROVE -> task:SCHEDULE_PAYMENT
- task:ENTER_RECORD -> task:UPDATE_RECORD
- task:REJECT -> task:NOTIFY
- task:UPDATE_RECORD -> task:APPROVE

### Edges removed in B
- event:start -> task:RECEIVE_MESSAGE
- gw:APPROVE_OR_REJECT ->|reject| task:NOTIFY
- gw:HAS_PO ->|no_po| task:ROUTE_FOR_REVIEW
- task:ENTER_RECORD -> task:SCHEDULE_PAYMENT
- task:EXECUTE_PAYMENT -> end:end
- task:RECEIVE_MESSAGE -> gw:HAS_PO

### Unknowns added in B
- Approval authority mentioned without explicit threshold/criteria: 'The manager must confirm the expense and provide an account code.' — what is the dollar threshold or rule that triggers this approver?
- Decision detected but branches not fully modeled: 'If an invoice does not have a PO number, AP routes it to the department manager.' — what are the explicit outcomes and next steps?
- Decision detected but branches not fully modeled: 'If the manager rejects the expense, AP notifies the vendor and closes the invoice.' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- If the invoice DOES have a PO number, what is the standard AP path (2-way/3-way match, approvals)?
- What validation is required before routing to manager (vendor verification, duplicate invoice check)?
