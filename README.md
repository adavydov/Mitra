# Mitra MVP (constitution-centric)

## Нормативные документы
- Конституция: `governance/constitution.md`
- Нормативная иерархия: `governance/normative_hierarchy.md`

## Локальный запуск
```bash
pip install -r requirements.txt
uvicorn mitra_app.main:app --host 0.0.0.0 --port 10000
```

## Env vars
- `PORT`
- `TELEGRAM_WEBHOOK_SECRET`
- `ALLOWED_TELEGRAM_USER_IDS` (comma-separated IDs)
- `AUTONOMY_LEVEL`
- `RISK_APPETITE`
- `BUDGET_DAILY_LIMIT`
- `GOOGLE_DRIVE_FOLDER_ID` (optional; если нет — `Drive disabled`)
- `TELEGRAM_BOT_TOKEN` (только для `scripts/set_telegram_webhook.py`)
- `TELEGRAM_WEBHOOK_URL` (только для `scripts/set_telegram_webhook.py`)

## Render deploy
- Используется `render.yaml`
- Start command: `uvicorn mitra_app.main:app --host 0.0.0.0 --port $PORT`

## Audit / Evidence
Каждое webhook-действие пишет audit-событие в stdout (JSON):
- событие intake,
- решение policy,
- попытка/результат создания report-артефакта.
