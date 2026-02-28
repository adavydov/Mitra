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

## 6) KPI Dashboard
- % задач, где Митра сама выявила gaps: `<pct_mitra_detected_gaps>`
- % задач, дошедших Telegram→Deploy без ручных правок: `<pct_telegram_to_deploy_without_manual_edits>`
- Median cycles-to-merge: `<median_cycles_to_merge>`
- Top recurring missing capabilities:
<top_recurring_missing_capabilities>

## 7) KPI Threshold Alerts
<kpi_alerts>
