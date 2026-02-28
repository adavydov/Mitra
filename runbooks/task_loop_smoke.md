# Task Loop Smoke Test
ID: RB-TASK-LOOP-01
Level: L3
Depends on: Telegram webhook, GitHub Actions callback

## Цель
Проверить полный цикл `/task -> GitHub issue -> Codex PR -> merge -> Telegram статус`.

## Пример команды
`/task Добавь команду /hello которая отвечает "hello from mitra" и покрыта тестом.`

## Ожидаемые сигналы
1. Mitra отвечает ссылкой на issue и ожидаемой новой командой `/hello`.
2. В админ-чат приходит событие `PR открыт`.
3. В админ-чат приходит событие `PR смержен`.
4. После деплоя `/hello` возвращает `hello from mitra`.


## CI: smoke vs full
- `ci/smoke` (для каждого PR после `ci/lint`) проверяет только быстрый контур: компиляцию Python-модулей, импорт `mitra_app.main` и `tests/test_import_smoke.py` с проверкой `/healthz`.
- `ci/tests-full` выполняет полный `pytest -q` и включается для более дорогой регрессии: на `push` в `main`, вручную через `workflow_dispatch`, либо в PR с label `full-tests`.
- Ожидание для PR: зелёный `ci/smoke` обязателен по умолчанию; `ci/tests-full` запускается по необходимости.


## Обязательный smoke-сценарий: calendar task-loop E2E
1. Запустить диалог командой `/task` с календарным запросом без полного контекста (например, про синхронизацию calendar/webhook).
2. Дать неоднозначные ответы на уточнения (provider/credentials), включая попытку прислать секрет в явном виде.
3. Проверить, что внутри активного диалога нет ответа `Unknown command` и после уточнений создаётся issue.
4. Проверить, что issue создан с label `mitra:codex`, содержит `Capability gaps` секции и блок `Контекст уточнений` с календарным контекстом.
5. Проверить аудит-событие `telegram_task_open_issue`: есть диагностические поля `detected_intents`, `matched_capabilities`, `capability_gaps`, `outcome`.
6. Проверить, что значение секрета не попало в логи (caplog/audit payload).

Референс-тест: `tests/test_telegram_webhook.py::test_task_command_multiturn_calendar_e2e_handles_ambiguous_answers_secret_and_creates_issue`.
