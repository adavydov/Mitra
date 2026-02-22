# Render
ID: CAP-RENDER-01
Owner: User
Depends on: C-TOOLS-01, P-ACCESS-01

## Назначение
Исполняемая runtime-среда.
## Требуемые права
Deploy, env vars, healthcheck.
## Риски
Неверный деплой/утечка секретов.
## Ограничения
Rollback обязателен при инцидентах.
## Логи/следы
deploy id, healthcheck result.
## Required evals
EVAL-REG-01
REF: PR-CHG-01
