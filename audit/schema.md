# Audit Event Schema

Каждое внешнее действие записывается как одна JSON-строка (NDJSON) в `audit/events.ndjson`.

## Обязательные поля
- `timestamp` — UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SS.mmmmmm+00:00`).
- `actor` — субъект действия (`user:<id>`, `system:<service>`, `agent:<name>`).
- `request_id` — сквозной идентификатор запроса.
- `policy_ids` — массив policy ID, применённых при действии.
- `protocol_ids` — массив protocol ID, применённых при действии.
- `tool_call` — объект вида:
  - `name` — имя внешнего инструмента (`telegram.reply`, `drive.write`).
  - `target` — получатель/ресурс (`chat_id`, путь/ID файла).
  - `args_hash` — контрольный hash аргументов (без чувствительных данных).
- `outcome` — `allowed | denied | error`.
- `rollback_pointer` — ссылка на откат (`rollback://...`) или `null`, если не требуется.
- `execution_id` — короткий ID исполнения для user-facing evidence.
- `evidence_uri` — URI записи события (`audit://events/<request_id>/<execution_id>`).

## Пример
```json
{"timestamp":"2026-02-22T10:15:01.123456+00:00","actor":"agent:mitra","request_id":"req-7f2","policy_ids":["C-OBS-01"],"protocol_ids":["IR-LOG-02"],"tool_call":{"name":"telegram.reply","target":"chat:12345","args_hash":"sha256:ab12..."},"outcome":"allowed","rollback_pointer":"rollback://telegram/chat:12345/msg:67890","execution_id":"ex-9F3A1C","evidence_uri":"audit://events/req-7f2/ex-9F3A1C"}
```
