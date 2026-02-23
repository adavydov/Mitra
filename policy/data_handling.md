ID: P-DATA-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, C-PRIV-01
Config keys: CFG-DENY-01
Required evals: EVAL-PRIV-AUDIT-01

# Data Handling Policy
## Decision rules
- Логировать только минимальный контекст.
- Сообщение хранить в hashed/snippet виде.
- Секреты и токены маскировать.
