# Gap Analysis Report

Comparison of each sub-document's auto-extracted process against the Master Manual (`ap_master_manual_auto`).

> **Missing Step** — intent present in the sub-document but absent from the Master Manual.
> **Missing Logic Path** — directed edge (A → B) present in the sub-document but absent from the Master Manual.

## doc_001

### Steps present in sub-doc but absent from Master Manual

| # | Canonical Key |
|---|---------------|
| 1 | `gw:MATCH_3_WAY` |

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `gw:MATCH_3_WAY` | `gw:THRESHOLD_AMOUNT` | `match` |
| 2 | `gw:THRESHOLD_AMOUNT` | `task:APPROVE` | `MATCH_3_WAY` |
| 3 | `task:VALIDATE_FIELDS` | `gw:MATCH_3_WAY` | _(unconditional)_ |

## doc_002

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `event:start` | `task:RECEIVE_MESSAGE` | _(unconditional)_ |
| 2 | `gw:APPROVE_OR_REJECT` | `task:ENTER_RECORD` | `no_po_approve` |
| 3 | `gw:APPROVE_OR_REJECT` | `task:NOTIFY` | `no_po_reject` |
| 4 | `gw:APPROVE_OR_REJECT` | `task:SCHEDULE_PAYMENT` | `no_po_approve` |
| 5 | `gw:APPROVE_OR_REJECT` | `task:UPDATE_STATUS` | `no_po_reject` |
| 6 | `gw:HAS_PO` | `task:ENTER_RECORD` | `no_po` |
| 7 | `gw:HAS_PO` | `task:REVIEW` | `no_po` |
| 8 | `gw:HAS_PO` | `task:ROUTE_FOR_REVIEW` | `no_po` |
| 9 | `task:ENTER_RECORD` | `gw:APPROVE_OR_REJECT` | _(unconditional)_ |
| 10 | `task:RECEIVE_MESSAGE` | `gw:HAS_PO` | _(unconditional)_ |
| 11 | `task:SCHEDULE_PAYMENT` | `end:end` | _(unconditional)_ |

## doc_003

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `event:start` | `task:MATCH_3_WAY` | _(unconditional)_ |
| 2 | `task:REQUEST_CLARIFICATION` | `task:UPDATE_RECORD` | _(unconditional)_ |

## doc_004

### Steps present in sub-doc but absent from Master Manual

_None — all step intents are covered by the Master Manual._

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `event:start` | `task:RECEIVE_MESSAGE` | _(unconditional)_ |
| 2 | `gw:APPROVE_OR_REJECT` | `task:SCHEDULE_PAYMENT` | `approve` |
| 3 | `gw:IF_CONDITION` | `task:RECEIVE_MESSAGE` | `condition_true` |
| 4 | `gw:IF_CONDITION` | `task:REQUEST_CLARIFICATION` | `condition_true` |
| 5 | `gw:IF_CONDITION` | `task:UPDATE_RECORD` | `condition_true` |
| 6 | `task:RECEIVE_MESSAGE` | `task:VALIDATE_FIELDS` | _(unconditional)_ |
| 7 | `task:ROUTE_FOR_REVIEW` | `gw:APPROVE_OR_REJECT` | _(unconditional)_ |
| 8 | `task:SCHEDULE_PAYMENT` | `end:end` | _(unconditional)_ |

## doc_005

### Steps present in sub-doc but absent from Master Manual

| # | Canonical Key |
|---|---------------|
| 1 | `task:REJECT` |

### Logic paths present in sub-doc but absent from Master Manual

| # | From (canonical) | To (canonical) | Condition |
|---|------------------|----------------|-----------|
| 1 | `gw:IF_CONDITION` | `task:EXECUTE_PAYMENT` | `successful_match` |
| 2 | `gw:IF_CONDITION` | `task:MATCH_3_WAY` | `not_duplicate` |
| 3 | `gw:IF_CONDITION` | `task:NOTIFY` | `duplicate_detected` |
| 4 | `gw:IF_CONDITION` | `task:REJECT` | `duplicate_detected` |

