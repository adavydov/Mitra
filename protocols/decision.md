ID: PR-DEC-01
Level: L2
Owner: Agent
Status: active
Depends on: P-ACCESS-01, P-BUDGET-01, P-SELF-01
Config keys: CFG-AUT-01, CFG-RISK-01, CFG-BUDGET-01
Required evals: EVAL-REG-HEALTH-01

# Decision Protocol
1) Применить policy engine.
2) Для /status вернуть конфигурацию.
3) Для /report создать артефакт в Drive или деградировать `Drive disabled`.
4) Всегда записать audit-событие.
