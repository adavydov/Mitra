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

## Scope control matrix

| Scope class | Path patterns | Default decision | Required approval labels |
|---|---|---|---|
| Auto-allowed paths | `mitra_app/*`, `tests/*`, `src/*` | allow | `mitra:codex` |
| Restricted paths | `governance/*`, `.github/workflows/*`, `policy/*` | deny unless override | `sovereign-override` (или `l0-approved`) |
| High-risk changes | `Risk level` = `R3`/`R4` или изменение restricted paths | pending approval | `security-review` + `governance-approved` |

## GitHub token controls
- Разрешён только `repo`-scoped токен (или fine-grained эквивалент с доступом к одному репозиторию).
- Принцип минимальных прав: 
  - read-only операции (`get_issue`, `list_prs`, `get_pr_status`) должны использовать только права чтения Issues/PR.
  - write-доступ должен использоваться только для `create_issue`.
- Токен не должен выводиться в логи, отчёты, трассировки и не должен храниться в коде/репозитории.

## Audit requirements
Логировать request_id, decision, reason, policy IDs, execution_id.
REF: L0-CONST
