# Mitra
Митра — симбиотический аватар Пользователя в цифровом мире: действует как продолжение воли Пользователя. Митра существует только в паре с Пользователем. Любая формальная система неизбежно встречает случаи, которые нельзя заранее полностью перечислить. Поэтому конституция включает «правило неизвестного случая» и протокол безопасного отката.

## Minimal Render Web Service

### Что добавлено
- Webhook listener: `POST /webhook`
- Healthcheck endpoint: `GET /healthz`
- Слои обработки:
  - `policy` — проверка секрета и типа события
  - `orchestrator` — маршрутизация задач (`sync`, `reconcile`, `noop`)
  - `evidence` — audit trail в JSONL

### Локальный запуск
```bash
export SERVICE_SHARED_SECRET="replace-me"
python service/app.py
```

### Тест webhook
```bash
curl -i -X POST http://localhost:10000/webhook \
  -H 'Content-Type: application/json' \
  -d '{"id":"evt-1","type":"sync","secret":"replace-me"}'
```

### Deploy на Render
1. Подключить репозиторий и использовать `render.yaml`.
2. Установить секрет `SERVICE_SHARED_SECRET` в Environment Variables.
3. (Опционально) переопределить `EVIDENCE_LOG_PATH`.
4. Проверить `GET /healthz` и отправить тестовый webhook.

Подробнее: `capabilities/render.md`, `policy/access_control.md`, `governance/codex/security.md`.
