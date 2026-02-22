# Incident Response Policy
ID: P-IR-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, C-SEC-01, C-OBS-01
Config keys: CFG-AUT-01
Required evals: EVAL-REG-01

## Intent
Реагирование на инциденты безопасности и audit gaps.

## Rules
- При компрометации/аномалии немедленный quarantine AL0.
- Запуск расследования и восстановление по rollback_pointer.
- Обязательный отчёт в reports и evidence в audit.

REF: L0-CONST
