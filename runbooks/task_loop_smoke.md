# Task Loop Smoke Test
ID: RB-TASK-LOOP-01
Level: L3
Depends on: Telegram webhook, GitHub Actions callback

## Цель
Проверить полный цикл `/task -> GitHub issue -> Codex PR -> merge -> Telegram статус`.

## Пример команды
`/task Добавь команду /hello которая отвечает "hello from mitra" и покрыта тестом.`

## Ожидаемые сигналы
1. Mitra отвечает ссылкой на issue и ожидаемой новой командой `/hello`.
2. В админ-чат приходит событие `PR открыт`.
3. В админ-чат приходит событие `PR смержен`.
4. После деплоя `/hello` возвращает `hello from mitra`.
