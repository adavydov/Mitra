# Periodic Audit Report Template

- Period: `<YYYY-MM-DD .. YYYY-MM-DD>`
- Prepared at: `<timestamp UTC>`
- Owner: `<team/person>`

## 1) Actions Summary
- Total external actions: `<count>`
- Telegram replies: `<count>`
- Drive writes: `<count>`
- Actions without rollback pointer: `<count>`

## 2) Incident Summary
| Incident ID | Class | Detected At | Requests Affected | Severity | Status |
|---|---|---|---|---|---|
| `<id>` | `IR-AUDIT-GAP` | `<timestamp>` | `<req ids>` | `<sev>` | `<open/closed>` |

## 3) Rollback Summary
| Rollback ID | Trigger | Pointer | Started | Completed | Result |
|---|---|---|---|---|---|
| `<rb-id>` | `<incident/tool>` | `rollback://...` | `<timestamp>` | `<timestamp>` | `<ok/partial/fail>` |

## 4) Exceptions and Gaps
- Missing events: `<count>`
- Reconstructed events: `<count>`
- Known limitations: `<items>`

## 5) Evidence
- Audit source: `audit/events.ndjson`
- Sample execution IDs: `<ex-XXXXXX, ex-YYYYYY>`
- Linked incidents: `<ticket links>`
