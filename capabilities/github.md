# GitHub
ID: CAP-GH-01
Owner: User
Depends on: C-TOOLS-01, P-ACCESS-01

## Назначение
GitOps и PR workflow через GitHub API.

## Env
- `GITHUB_TOKEN` — токен доступа к GitHub API.
- `GITHUB_REPO` — репозиторий в формате `owner/repo`.

## API-функции (v1)
- `create_issue(title, body, labels)` — создать issue.
- `get_issue(number)` — получить issue по номеру.
- `list_prs(state=open)` — получить список PR (read-only).
- `get_pr_status(number)` — получить статус PR (read-only).

## Минимальные права токена
- Для `create_issue`: `Issues: Read and write` (или классический `repo` для private репозитория).
- Для `get_issue`, `list_prs`, `get_pr_status`: `Pull requests: Read`, `Issues: Read`.
- Предпочтителен fine-grained PAT с доступом только к одному репозиторию.

## Риски
- Утечка `GITHUB_TOKEN` позволяет выполнять API-вызовы от имени владельца токена.
- Избыточные права токена могут привести к модификации кода/настроек репозитория.
- Неконтролируемое создание issue может привести к спаму и операционным затратам.

## Контрмеры
- Использовать токен минимально необходимого scope.
- Хранить токен только в secret storage, не логировать и не коммитить.
- Ограничивать операции записью только там, где это нужно (`create_issue`).

## Required evals
EVAL-REG-01
REF: P-ACCESS-01
