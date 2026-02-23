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
  - `ci/config-validate` — validates config schemas.
  - `ci/tests` — runs regression evals after lint/config checks.
