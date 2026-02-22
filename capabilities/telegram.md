# CAP-TG-01 — Telegram capability

## Required rights
- Созданный Telegram bot token (через BotFather).
- Права на установку webhook (`setWebhook`) на публичный HTTPS URL Render.
- Доступ runtime к переменным:
  - `TELEGRAM_BOT_TOKEN` (секрет).
  - `TELEGRAM_WEBHOOK_SECRET` (verify secret header).
  - `AUTONOMY_LEVEL`, `RISK_APPETITE`.
- Логи приложения только с редактированными (redacted) данными.

## Риски
- **Spoofed webhook**: поддельные POST без валидации секрета.
- **PII leakage**: текст сообщений содержит персональные данные.
- **Prompt abuse**: попытки инициировать запрещённые действия.
- **Overreach**: выполнение действий при несоответствующем уровне автономии/риска.

## Ограничения
- MVP-классификация только по текстовым эвристикам.
- Обрабатываются классы:
  - `report_document_request`
  - `unknown`
  - `restricted`
- Вложения (`document`) учитываются только как контекст, без скачивания содержимого.
- `restricted` не эскалируется к авто-выполнению и всегда блокируется.

## Required evals
1. **Classification eval**:
   - balanced набор примеров для 3 классов,
   - метрики: precision/recall/F1 по каждому классу.
2. **Policy-gate eval**:
   - проверка блокировок при низком `AUTONOMY_LEVEL` и/или `RISK_APPETITE`.
3. **Webhook auth eval**:
   - позитив/негатив тесты для `X-Telegram-Bot-Api-Secret-Token`.
4. **PII redaction eval**:
   - маскирование телефонов, email, токенов, длинных числовых идентификаторов в логах.
