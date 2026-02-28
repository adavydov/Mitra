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

## Telegram task/command event fields

Для событий `telegram_task_open_issue` и `telegram_unknown_command` используются дополнительные поля расследования:

- `request_intents` — intents, извлечённые из `/task`-запроса.
- `matched_capabilities` — capability IDs, найденные в каталоге.
- `detected_gaps` — gaps (`code|policy|config|tests|secrets|runbook`), которые нужно закрыть.
- `parse_outcome` — исход парсинга task spec: `primary | retry | fallback`.
- `risk_level` — нормализованный риск (`R0..R4`).
- `allowed_file_scope` — допустимые пути изменения из task spec.
- `issue_url` — URL созданного issue (если issue создан).
- `dialog_state` — снимок текущего состояния task-диалога (`missing_fields`, `filled_fields_count`, `last_question_field`, `turns_count`) либо `null`.
- `reason_code` — код причины для отказов/игнорирования (например `unknown_command`).

## Пример
```json
{"timestamp":"2026-02-22T10:15:01.123456+00:00","actor":"agent:mitra","request_id":"req-7f2","policy_ids":["C-OBS-01"],"protocol_ids":["IR-LOG-02"],"tool_call":{"name":"telegram.reply","target":"chat:12345","args_hash":"sha256:ab12..."},"outcome":"allowed","rollback_pointer":"rollback://telegram/chat:12345/msg:67890","execution_id":"ex-9F3A1C","evidence_uri":"audit://events/req-7f2/ex-9F3A1C"}
```

## Примеры расследования

### 1) Почему issue был создан через fallback
Проверяем, что `parse_outcome="fallback"`, и смотрим `detected_gaps` + `allowed_file_scope` для оценки, не ушёл ли task за безопасный scope.

### 2) Почему бот ответил `Unknown command`
Ищем событие `telegram_unknown_command`, сверяем `reason_code="unknown_command"` и `dialog_state`, чтобы понять, был ли активен незавершённый `/task` диалог.
