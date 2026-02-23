# Access Control
ID: P-ACCESS-01
Level: L2
Owner: User (merge)
Status: draft
Depends on: L0-CONST, C-SEC-01, C-TOOLS-01, L1-ID
Config keys: CFG-ALLOW-01
Required evals: EVAL-SEC-TG-SECRET-01, EVAL-SEC-TG-ALLOWLIST-01

## Intent
Контролировать входящие запросы и запрещать неавторизованные действия.

## Decision rules
- IF webhook secret header missing OR mismatch -> DENY (401)
- IF from.id not in allowlist -> DENY (403)
- ELSE -> ALLOW

## Audit requirements
- log: update_id, from.id, chat.id, decision, reason, timestamp
