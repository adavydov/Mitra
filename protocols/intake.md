# Intake Protocol
ID: PR-INTAKE-01
Level: L2
Depends on: P-ACCESS-01, P-DATA-01, C-AUT-01
Config keys: CFG-AUT-01, CFG-RISK-01
Required evals: EVAL-REG-01

## Inputs
Telegram update payload, AL/Risk context.

## Outputs
classification, decision, reason, request_id.

## Algorithm
1) Extract text/caption.
2) Classify as `report_document_request|unknown|restricted`.
3) Run policy gate by AL/Risk.
4) Emit intake decision and audit hooks.

## Fail-safe / rollback
Unknown or restricted input defaults to safe deny/no side effects.
REF: L0-CONST
