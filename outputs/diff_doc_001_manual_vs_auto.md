# Diff: doc_001_manual vs doc_001_auto

- A: `outputs/ap_doc_001.json`
- B: `outputs/ap_doc_001_auto.json`

## Summary

- Nodes: A=11  B=10  (+0 / -0)
- Edges: A=11  B=12  (+3 / -1)
- Unknowns: A=5  B=5  (+0 / -0)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- (none)

### Edges added in B
- gw:MATCH_3_WAY -> task:APPROVE
- gw:THRESHOLD_AMOUNT -> task:SCHEDULE_PAYMENT
- task:APPROVE -> gw:THRESHOLD_AMOUNT

### Edges removed in B
- task:APPROVE -> task:SCHEDULE_PAYMENT

### Unknowns added in B
- (none)

### Unknowns removed in B
- (none)
