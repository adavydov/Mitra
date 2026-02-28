# Self Modification Policy
ID: P-SELF-01
Level: L2
Owner: User (merge)
Status: active
Depends on: L0-CONST, C-EVO-01
Config keys: CFG-AUT-01, CFG-RISK-01
Required evals: EVAL-REG-01

## Intent
Ограничение самоизменений для сохранения обратимости.

## Rules
- По умолчанию self-modification запрещён.
- Разрешение только при user-approved режиме и с rollback checkpoint.
- Нарушение переводит систему в AL0.

## Change-scope matrix

| Scope class | Path patterns | Default decision | Required labels / overrides |
|---|---|---|---|
| Auto-allowed | `mitra_app/*`, `tests/*`, `src/*` | allow (если соблюдены AL/Risk policy) | `mitra:codex` |
| Restricted | `governance/*`, `.github/workflows/*`, `policy/*` | deny без явного override | `sovereign-override` (или legacy `l0-approved`) |
| High-risk change | Любой diff с `Risk level` = `R3`/`R4` ИЛИ изменение restricted scope | deny до аппрува | `security-review` и `governance-approved`, плюс override для restricted |

## Enforcement notes
- Для задач `/task` обязательны поля `Risk level` и `Allowed file scope`.
- CI валидирует, что фактический diff PR находится внутри заявленного `Allowed file scope`.
- Попытка изменить restricted scope без override label должна блокироваться policy deny.

REF: L0-CONST
