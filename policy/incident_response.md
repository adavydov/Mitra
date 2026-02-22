# Incident Response Policy

## IR-LOG-02 — Audit Gaps и Safe Rollback

Если обнаружен внешний эффект без audit event, это классифицируется как инцидент класса `IR-AUDIT-GAP`.

### Процедура
1. **Containment**: остановить соответствующий адаптер внешнего канала.
2. **Trace**: найти затронутые `request_id` и вычислить диапазон времени.
3. **Reconstruct**: попытаться восстановить события из вторичных логов.
4. **Rollback**: выполнить откат по `rollback_pointer`, где возможно.
5. **Notify**: уведомить владельца системы и Пользователя о масштабе.
6. **Report**: зафиксировать в периодическом отчёте секции Actions/Incidents/Rollbacks.

### SLA
- Triage: до 15 минут.
- Initial report: до 60 минут.
- Corrective action: до 24 часов.

### Артефакты
- `audit/events.ndjson`
- `reports/templates/periodic_audit_report.md`
- incident ticket с привязкой к `request_id`/`execution_id`
