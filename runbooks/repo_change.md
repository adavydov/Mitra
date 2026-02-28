# Repo Change Runbook
ID: RB-REPO-01
Level: L3
Depends on: PR-CHG-01, PR-VERIFY-01
Templates used: CFG-TPL-CHANGE
Audit: audit/events.ndjson

## Steps
1) Создать ветку proposals/*.
2) Внести изменения + тесты.
3) Если PR затрагивает `.github/workflows/*`, до запроса review добавить override-лейбл `sovereign-override` (или legacy `l0-approved`) согласно `.github/workflows/l0-guard.yml`.
4) В описании такого PR явно указать: `Touches protected perimeter (.github/workflows), override label applied`.
5) Если нужна политика без override для «безопасных» CI-изменений, обновлять `PROTECTED_PREFIXES`/логику в `.github/workflows/l0-guard.yml` только через отдельный governance-процесс.
6) Прогнать CI-гейты и оформить PR.
REF: L0-CONST
