# Data Handling Policy
ID: P-DATA-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, C-PRIV-01
Config keys: CFG-DENY-01
Required evals: EVAL-PRIV-LEAK-01

## Intent
Минимизация данных и защита приватности в intake/логах.

## Rules
- Сохранять только минимальные поля Telegram update.
- Перед логированием выполнять redaction.
- Не хранить секреты и содержимое вложений в audit.

## Audit requirements
Логировать факт redaction и перечень применённых масок.
REF: L0-CONST
