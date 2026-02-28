# Diff: doc_001_manual vs doc_001_auto

- A: `outputs/ap_doc_001.json`
- B: `outputs/ap_doc_001_auto.json`

## Summary

- Nodes: A=11  B=9  (+0 / -1)
- Edges: A=11  B=10  (+5 / -5)
- Unknowns: A=5  B=5  (+0 / -0)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- task:RECEIVE_MESSAGE

### Edges added in B
- event:start -> task:ENTER_RECORD
- gw:THRESHOLD_AMOUNT ->|amount<=thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|match_3_way| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|schedule_payment| task:EXECUTE_PAYMENT

### Edges removed in B
- event:start -> task:RECEIVE_MESSAGE
- gw:THRESHOLD_AMOUNT ->|amount<=5000| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>5000| task:APPROVE
- task:RECEIVE_MESSAGE -> task:ENTER_RECORD
- task:SCHEDULE_PAYMENT -> task:EXECUTE_PAYMENT

### Unknowns added in B
- (none)

### Unknowns removed in B
- (none)
