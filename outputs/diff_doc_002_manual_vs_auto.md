# Diff: doc_002_manual vs doc_002_auto

- A: `outputs/ap_doc_002.json`
- B: `outputs/ap_doc_002_auto.json`

## Summary

- Nodes: A=12  B=12  (+0 / -0)
- Edges: A=11  B=11  (+2 / -2)
- Unknowns: A=5  B=5  (+2 / -2)
- Evidence coverage (node-level): A=100.00%  B=91.67%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- (none)

### Edges added in B
- gw:APPROVE_OR_REJECT -> end:end
- gw:HAS_PO -> task:ROUTE_FOR_REVIEW

### Edges removed in B
- gw:HAS_PO ->|no_po| task:ROUTE_FOR_REVIEW
- task:EXECUTE_PAYMENT -> end:end

### Unknowns added in B
- Approval authority mentioned without explicit threshold/criteria: 'The manager must confirm the expense and provide an account code.' — what is the dollar threshold or rule that triggers this approver?
- Decision detected but branches not fully modeled: 'If an invoice does not have a PO number, AP routes it to the department manager.' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- If the invoice DOES have a PO number, what is the standard AP path (2-way/3-way match, approvals)?
- What validation is required before routing to manager (vendor verification, duplicate invoice check)?
