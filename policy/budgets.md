# Budget Policy
ID: P-BUDGET-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, C-FIN-01
Config keys: CFG-BUDGET-01
Required evals: EVAL-FIN-BUDGET-01

## Intent
Ограничивает расходы по дневному окну и per-action лимитам.

## Decision rules
- IF projected_spend > hard_limit THEN deny.
- IF tool_cost undefined THEN deny.
- IF cost > AL.max_budget_per_action THEN deny.
- ELSE allow; при soft_limit — warning.

## Audit requirements
Фиксировать до/после spend и причину deny.
REF: L0-CONST
