# Mitra
Митра — симбиотический аватар Пользователя в цифровом мире: действует как продолжение воли Пользователя.

## Runtime (Render)
- Webhook endpoint: `POST /webhook/telegram`
- Healthcheck: `GET /healthz`
- Перед выполнением действий включены:
  - классификация запроса (`report_document_request | unknown | restricted`)
  - policy gate по `Autonomy Level` и `Risk Appetite`

См. протоколы и политики:
- `protocols/intake.md` (`PR-INTAKE-01`)
- `capabilities/telegram.md` (`CAP-TG-01`)
- `policy/access_control.md`
- `policy/data_handling.md`

## How CI works
- GitHub Actions workflow: `.github/workflows/ci.yml`.
- Triggers: every pull request and every push to `main`.
- Stable branch-protection checks:
  - `ci/lint` — validates IDs.
  - `ci/smoke` — быстрые smoke-проверки импорта и `/healthz` (`py_compile`, import, `tests/test_import_smoke.py`).
  - `ci/tests-full` — полный `pytest -q`; запускается на `push` в `main`, вручную через `workflow_dispatch` или в PR с label `full-tests`.

## Workflow PR governance guard
- Если PR изменяет `.github/workflows/**`, обязателен override label: `sovereign-override` (или legacy `l0-approved`).
- Это отдельная governance/security-проверка (L0 guard), а не результат unit/integration тестов.
