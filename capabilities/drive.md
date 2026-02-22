# Google Drive
ID: CAP-DRIVE-01
Owner: User
Depends on: C-TOOLS-01, P-ACCESS-01

## Назначение
Создание документов/артефактов.
## Требуемые права
Ограниченный scope на создание/шаринг файлов.
## Риски
Перешаривание данных.
## Ограничения
Только отчётные артефакты из runbooks.
## Логи/следы
file_id, link, execution_id.
## Required evals
EVAL-PRIV-LEAK-01
REF: P-DATA-01
