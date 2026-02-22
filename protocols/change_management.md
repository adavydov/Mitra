# Protocol: Change Management и rollback релиза

## Перед релизом
- Проверить changelog и влияние на policy/evidence слои.
- Убедиться, что заданы env vars: `SERVICE_SHARED_SECRET`, `EVIDENCE_LOG_PATH` (опционально).
- Выполнить локальные smoke-тесты.

## Деплой
1. Запустить deploy через Render с указанием целевой ветки.
2. Проверить успешный старт процесса и endpoint `/healthz`.
3. Отправить тестовый webhook с валидным секретом.

## Откат
1. В Render выбрать предыдущий стабильный deploy и нажать rollback.
2. Проверить `/healthz` после rollback.
3. Повторить тестовый webhook и сверить evidence.
4. Зафиксировать rollback в журнале изменений с причиной.
