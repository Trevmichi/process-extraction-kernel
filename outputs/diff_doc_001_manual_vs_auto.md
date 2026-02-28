# Diff: doc_001_manual vs doc_001_auto

- A: `outputs/ap_doc_001.json`
- B: `outputs/ap_doc_001_auto.json`

## Summary

- Nodes: A=11  B=10  (+0 / -0)
- Edges: A=11  B=11  (+3 / -2)
- Unknowns: A=5  B=5  (+0 / -0)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- (none)

### Edges added in B
- gw:THRESHOLD_AMOUNT ->|amount<=thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>thresh| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|match_3_way| task:APPROVE

### Edges removed in B
- gw:THRESHOLD_AMOUNT ->|amount<=5000| task:APPROVE
- gw:THRESHOLD_AMOUNT ->|amount>5000| task:APPROVE

### Unknowns added in B
- (none)

### Unknowns removed in B
- (none)
