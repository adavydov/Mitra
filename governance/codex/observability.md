# Codex Observability Requirements

## C-OBS-01 — Mandatory Audit for External Side Effects

Все внешние действия MUST быть аудированы до фактического вызова инструмента. Внешним действием считается операция, изменяющая внешнее состояние или отправляющая данные за пределы runtime (например, `telegram.reply`, `drive.write`).

### Требования
1. Runtime перед каждым внешним действием создаёт `execution_id` и резервирует audit event.
2. Вызов внешнего инструмента запрещён, если audit event не удалось записать.
3. Каждое событие содержит: `timestamp`, `actor`, `request_id`, `policy_ids`, `protocol_ids`, `tool_call`, `outcome`, `rollback_pointer`.
4. Ответ пользователю должен включать ссылку на evidence в компактном виде: `execution_id`.
5. Для `outcome=error|denied` обязателен `rollback_pointer` (или явное `null` с причиной в incident report).

### Контроль соответствия
- Unit-level: middleware тестирует fail-closed поведение при сбое writer.
- Runtime-level: алерт при обнаружении внешнего действия без связанного `execution_id`.
- Reporting-level: ежепериодная сверка `reports/` с `audit/events.ndjson`.
