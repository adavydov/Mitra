ID: C-SEC-01
Level: L1
Owner: User
Status: active
Depends on: L0-CONST, L1-ID
Config keys: CFG-ALLOW-01, CFG-DENY-01, CFG-TOOLS-01
Required evals: EVAL-SEC-WEBHOOK-01

# Security Codex
## Запреты
- Нельзя выполнять запрос без webhook secret.
- Нельзя выполнять запрос от неразрешённого пользователя.
- Нельзя использовать неизвестные инструменты.
