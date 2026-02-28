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
- Triggers:
  - `pull_request` (`opened`, `synchronize`, `reopened`) — запускаются `ci/scope-check`, `ci/lint`, `ci/smoke`.
  - `push` в `main` — запускаются `ci/lint`, `ci/smoke`.
  - `workflow_dispatch` — ручной запуск.
- Stable checks and roles:
  - `ci/scope-check` — **policy-gate только для PR** (governance/security проверка изменений и declared scope).
  - `ci/lint` — техническая проверка (базовая валидация/компиляция).
  - `ci/smoke` — **технический smoke-job**, зависит только от `ci/lint` (быстрые проверки импорта: `py_compile`, import, `tests/test_import_smoke.py`).
  - `ci/tests-full` — полный `pytest -q`; запускается вручную через `workflow_dispatch` или в PR с label `full-tests`.

## Workflow PR governance guard
- Если PR изменяет `.github/workflows/**`, обязателен override label: `sovereign-override` (или legacy `l0-approved`).
- Это отдельная governance/security-проверка (L0 guard), а не результат unit/integration тестов.
