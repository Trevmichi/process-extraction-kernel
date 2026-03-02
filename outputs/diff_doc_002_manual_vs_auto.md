# Diff: doc_002_manual vs doc_002_auto

- A: `outputs/ap_doc_002.json`
- B: `outputs/ap_doc_002_auto.json`

## Summary

- Nodes: A=12  B=12  (+1 / -2)
- Edges: A=11  B=11  (+10 / -10)
- Unknowns: A=5  B=3  (+0 / -2)
- Evidence coverage (node-level): A=100.00%  B=91.67%

## Details

### Nodes added in B
- task:UPDATE_STATUS

### Nodes removed in B
- task:EXECUTE_PAYMENT
- task:UPDATE_RECORD

### Edges added in B
- gw:APPROVE_OR_REJECT ->|no_po_approve| task:ENTER_RECORD
- gw:APPROVE_OR_REJECT ->|no_po_approve| task:SCHEDULE_PAYMENT
- gw:APPROVE_OR_REJECT ->|no_po_reject| task:NOTIFY
- gw:APPROVE_OR_REJECT ->|no_po_reject| task:UPDATE_STATUS
- gw:HAS_PO ->|no_po| task:ENTER_RECORD
- gw:HAS_PO ->|no_po| task:REVIEW
- task:ENTER_RECORD -> gw:APPROVE_OR_REJECT
- task:RECEIVE_MESSAGE -> task:ROUTE_FOR_REVIEW
- task:ROUTE_FOR_REVIEW -> gw:HAS_PO
- task:SCHEDULE_PAYMENT -> end:end

### Edges removed in B
- gw:APPROVE_OR_REJECT ->|approve| task:ENTER_RECORD
- gw:APPROVE_OR_REJECT ->|reject| task:NOTIFY
- gw:HAS_PO ->|no_po| task:ROUTE_FOR_REVIEW
- task:ENTER_RECORD -> task:SCHEDULE_PAYMENT
- task:EXECUTE_PAYMENT -> end:end
- task:RECEIVE_MESSAGE -> gw:HAS_PO
- task:REVIEW -> task:UPDATE_RECORD
- task:ROUTE_FOR_REVIEW -> task:REVIEW
- task:SCHEDULE_PAYMENT -> task:EXECUTE_PAYMENT
- task:UPDATE_RECORD -> gw:APPROVE_OR_REJECT

### Unknowns added in B
- (none)

### Unknowns removed in B
- If the invoice DOES have a PO number, what is the standard AP path (2-way/3-way match, approvals)?
- What validation is required before routing to manager (vendor verification, duplicate invoice check)?
