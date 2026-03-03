# Gap Analysis Report

Comparison of each sub-document's auto-extracted process against the Master Manual (`ap_master_manual_auto`).

> **Missing Step** — intent present in the sub-document but absent from the Master Manual.
> **Missing Logic Path** — directed edge (A → B) present in the sub-document but absent from the Master Manual.

## doc_001

### Steps present in sub-doc but absent from Master Manual

| # | Canonical Key |
|---|---------------|
| 1 | `gw:THRESHOLD_AMOUNT` |

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `gw:MATCH_3_WAY` | `gw:THRESHOLD_AMOUNT` | `match` |
| 2 | `gw:THRESHOLD_AMOUNT` | `task:APPROVE` | `amount<=THRESH` |
| 3 | `gw:THRESHOLD_AMOUNT` | `task:APPROVE` | `amount>THRESH` |
| 4 | `task:APPROVE` | `task:SCHEDULE_PAYMENT` | _(unconditional)_ |
| 5 | `task:SCHEDULE_PAYMENT` | `task:EXECUTE_PAYMENT` | _(unconditional)_ |

## doc_002

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `gw:APPROVE_OR_REJECT` | `task:NOTIFY` | `APPROVE_OR_REJECT_false` |
| 2 | `gw:APPROVE_OR_REJECT` | `task:SCHEDULE_PAYMENT` | `APPROVE_OR_REJECT_true` |
| 3 | `gw:APPROVE_OR_REJECT` | `task:UPDATE_STATUS` | `APPROVE_OR_REJECT_false` |
| 4 | `gw:HAS_PO` | `task:ENTER_RECORD` | `HAS_PO_false` |
| 5 | `gw:HAS_PO` | `task:REVIEW` | `HAS_PO_false` |
| 6 | `task:ENTER_RECORD` | `gw:APPROVE_OR_REJECT` | _(unconditional)_ |
| 7 | `task:RECEIVE_MESSAGE` | `task:ROUTE_FOR_REVIEW` | _(unconditional)_ |
| 8 | `task:ROUTE_FOR_REVIEW` | `gw:HAS_PO` | _(unconditional)_ |
| 9 | `task:SCHEDULE_PAYMENT` | `end:end` | _(unconditional)_ |

## doc_003

### Steps present in sub-doc but absent from Master Manual

| # | Canonical Key |
|---|---------------|
| 1 | `gw:VARIANCE_ABOVE_TOLERANCE` |

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `event:start` | `task:MATCH_3_WAY` | _(unconditional)_ |
| 2 | `gw:VARIANCE_ABOVE_TOLERANCE` | `task:REQUEST_CLARIFICATION` | `VARIANCE_ABOVE_TOLERANCE` |
| 3 | `task:MATCH_3_WAY` | `gw:VARIANCE_ABOVE_TOLERANCE` | _(unconditional)_ |
| 4 | `task:REQUEST_CLARIFICATION` | `task:UPDATE_RECORD` | _(unconditional)_ |

## doc_004

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `gw:APPROVE_OR_REJECT` | `task:SCHEDULE_PAYMENT` | `approve` |
| 2 | `gw:IF_CONDITION` | `task:ENTER_RECORD` | `condition_true` |
| 3 | `gw:IF_CONDITION` | `task:REQUEST_CLARIFICATION` | `condition_true` |
| 4 | `gw:IF_CONDITION` | `task:UPDATE_RECORD` | `condition_true` |
| 5 | `task:ROUTE_FOR_REVIEW` | `gw:APPROVE_OR_REJECT` | _(unconditional)_ |
| 6 | `task:SCHEDULE_PAYMENT` | `end:end` | _(unconditional)_ |
| 7 | `task:UPDATE_RECORD` | `task:ROUTE_FOR_REVIEW` | _(unconditional)_ |

## doc_005

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `event:start` | `task:ENTER_RECORD` | _(unconditional)_ |
| 2 | `gw:IF_CONDITION` | `task:EXECUTE_PAYMENT` | `successful_match` |
| 3 | `gw:IF_CONDITION` | `task:MATCH_3_WAY` | `not_duplicate` |
| 4 | `gw:IF_CONDITION` | `task:NOTIFY` | `duplicate_detected` |
| 5 | `gw:IF_CONDITION` | `task:REJECT` | `duplicate_detected` |

