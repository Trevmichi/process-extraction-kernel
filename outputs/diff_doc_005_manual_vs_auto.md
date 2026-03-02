# Diff: doc_005_manual vs doc_005_auto

- A: `outputs/ap_doc_005.json`
- B: `outputs/ap_doc_005_auto.json`

## Summary

- Nodes: A=11  B=8  (+0 / -3)
- Edges: A=10  B=7  (+6 / -9)
- Unknowns: A=3  B=4  (+1 / -0)
- Evidence coverage (node-level): A=100.00%  B=100.00%

## Details

### Nodes added in B
- (none)

### Nodes removed in B
- end:paid
- task:RECEIVE_MESSAGE
- task:VALIDATE_FIELDS

### Edges added in B
- event:start -> task:ENTER_RECORD
- gw:IF_CONDITION ->|duplicate_detected| task:NOTIFY
- gw:IF_CONDITION ->|duplicate_detected| task:REJECT
- gw:IF_CONDITION ->|successful_match| task:EXECUTE_PAYMENT
- task:ENTER_RECORD -> gw:IF_CONDITION
- task:EXECUTE_PAYMENT -> end:end

### Edges removed in B
- event:start -> task:RECEIVE_MESSAGE
- gw:IF_CONDITION ->|duplicate| task:REJECT
- task:ENTER_RECORD -> task:VALIDATE_FIELDS
- task:EXECUTE_PAYMENT -> end:paid
- task:MATCH_3_WAY -> task:EXECUTE_PAYMENT
- task:NOTIFY -> end:end
- task:RECEIVE_MESSAGE -> task:ENTER_RECORD
- task:REJECT -> task:NOTIFY
- task:VALIDATE_FIELDS -> gw:IF_CONDITION

### Unknowns added in B
- Decision detected but branches not fully modeled: 'The system checks for duplicate invoice numbers' — what are the explicit outcomes and next steps?

### Unknowns removed in B
- (none)
