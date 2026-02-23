# Telegram Intake
ID: PR-INTAKE-01
Level: L2
Owner: Agent
Status: active
Depends on: P-ACCESS-01, CAP-TG-01
Config keys: CFG-ALLOW-01
Required evals: EVAL-REG-INTAKE-01

## Inputs
- Telegram Update (JSON)

## Outputs
- Normalized Intent: status|report|help|unknown

## Algorithm
1) Validate webhook secret token header
2) Extract update_id + message.text + from.id + chat.id
3) Enforce allowlist
4) Classify by leading command:
   - /status -> status
   - /report -> report
   - /help or /start -> help
   - else -> unknown
5) Emit audit event with decision and intent
