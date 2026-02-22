# Access Control Policy
ID: P-ACCESS-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, L1-ID, C-AUT-01, C-SEC-01
Config keys: CFG-AUT-01, CFG-TOOLS-01
Required evals: EVAL-SEC-TOOLCALL-01

## Intent
Регулирует допустимые действия по AL/Risk и правам инструментов.

## Decision rules
- IF classification=restricted THEN deny.
- IF AL/Risk ниже требуемых порогов THEN deny.
- ELSE allow только для разрешённых инструментов.

## Audit requirements
Логировать request_id, decision, reason, policy IDs, execution_id.
REF: L0-CONST
