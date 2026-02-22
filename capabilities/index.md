# Capabilities Registry

This registry maps tools/capabilities to governing sources without duplicating logic.

| Capability | Primary owner | Governed by policy | Mandated by codex | Protocol link | Runbook link | Config keys |
|---|---|---|---|---|---|---|
| Change Management | Platform Team | `policy/B-policy.md` | `governance/A-codex.md` | `protocols/C-protocol.md` | `runbooks/D-runbook.md` | `protocols.change.freeze_windows`, `runbooks.slo.response_minutes` |
| Incident Response | Operations Team | `policy/B-policy.md` | `governance/A-codex.md` | `protocols/C-protocol.md` | `runbooks/D-runbook.md` | `runbooks.incident.escalation_matrix` |
| Compliance Evidence | Internal Audit | `policy/B-policy.md` | `governance/A-codex.md` | `protocols/C-protocol.md` | `runbooks/D-runbook.md` | `audit.log.retention_days`, `audit.evidence.minimum_set` |
| KPI Reporting | PMO | `policy/B-policy.md` | `governance/A-codex.md` | `protocols/C-protocol.md` | `runbooks/D-runbook.md` | `reports.kpi.catalog`, `reports.publication.schedule` |

## Notes
- Policy defines constraints.
- Codex defines strategic intent.
- Protocol defines workflow.
- Runbook defines executable operations.
- Config defines tunable values.
