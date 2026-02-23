# Telegram
ID: CAP-TG-01
Level: H
Owner: User
Depends on: L0-CONST, C-TOOLS-01, P-ACCESS-01
Status: draft
Config keys: CFG-ALLOW-01
Required evals: EVAL-SEC-TG-SECRET-01, EVAL-SEC-TG-ALLOWLIST-01

## Назначение
Единственный пользовательский интерфейс MVP: входящие сообщения и исходящие ответы.

## Входы/выходы
- In: Telegram Update (webhook)
- Out: sendMessage (Bot API)

## Требуемые права
- TELEGRAM_BOT_TOKEN (secret)
- Webhook endpoint доступен по HTTPS

## Риски
- Подмена источника webhook
- Спам/ддос в endpoint
- Неправильная авторизация пользователя

## Ограничения
- Принимать только allowlisted user_id
- Проверять secret_token заголовок
- allowed_updates минимизировать (message)

## Логи/следы
- Каждое обновление: update_id, from.id, chat.id, route, решение allow/deny, timestamp

## Required evals
- EVAL-SEC-TG-SECRET-01
- EVAL-SEC-TG-ALLOWLIST-01
