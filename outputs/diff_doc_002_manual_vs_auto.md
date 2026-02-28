# Diff: doc_002_manual vs doc_002_auto

- A: `outputs/ap_doc_002.json`
- B: `outputs/ap_doc_002_auto.json`

## Summary

- Nodes: A=12  B=5  (+1 / -10)
- Edges: A=11  B=4  (+3 / -11)
- Unknowns: A=5  B=6  (+5 / -4)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- gw:IF_CONDITION

### Nodes removed in B
- gw:APPROVE_OR_REJECT
- gw:HAS_PO
- task:ENTER_RECORD
- task:EXECUTE_PAYMENT
- task:NOTIFY
- task:RECEIVE_MESSAGE
- task:REVIEW
- task:ROUTE_FOR_REVIEW
- task:SCHEDULE_PAYMENT
- task:UPDATE_RECORD

### Edges added in B
- event:start -> gw:IF_CONDITION
- gw:IF_CONDITION -> end:end
- gw:IF_CONDITION -> gw:IF_CONDITION

### Edges removed in B
- event:start -> task:RECEIVE_MESSAGE
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
- Approval authority mentioned without explicit threshold/criteria: 'The manager must confirm the expense and provide an account code.' — what is the dollar threshold or rule that triggers this approver?
- Could not map sentence to an atomic action: 'The manager must confirm the expense and provide an account code.' — what action(s) should this become?
- Decision detected but branches not fully modeled: 'If approved, AP enters the account code and proceeds to schedule payment.' — what are the explicit outcomes and next steps?
- Decision detected but branches not fully modeled: 'If the manager rejects the expense, AP notifies the vendor and closes the invoice.' — what are the explicit outcomes and next steps?
- Decision detected but branches not fully modeled: '﻿If an invoice does not have a PO number, AP routes it to the department manager.' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- If the invoice DOES have a PO number, what is the standard AP path (2-way/3-way match, approvals)?
- If the invoice HAS a PO number, what is the standard path (2-way vs 3-way match, approvals)?
- What are the payment terms (Net 30/45/60) and are there early-pay discounts?
- What validation is required before routing to manager (vendor verification, duplicate invoice check)?
