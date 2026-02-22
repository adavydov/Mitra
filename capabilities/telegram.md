# Telegram
ID: CAP-TG-01
Owner: User
Depends on: C-TOOLS-01, P-ACCESS-01

## Назначение
Intake и ответы пользователю.
## Требуемые права
Webhook secret, send_message.
## Риски
Injection, PII leakage.
## Ограничения
Только allowlisted chat flows.
## Логи/следы
execution_id + request_id в audit.
## Required evals
EVAL-SEC-INJECT-01, EVAL-PRIV-LEAK-01
REF: P-ACCESS-01
