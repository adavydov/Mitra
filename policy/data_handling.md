# Data Handling Policy

## Классы данных из Telegram
Допустимые входные поля для intake:
- `update_id`
- `message.text` / `message.caption`
- `message.chat.id`
- `message.from.id`
- `message.date`
- `message.document.file_name|mime_type|file_size` (без загрузки файла)

Недопустимо сохранять/логировать:
- полный bot token, webhook secret,
- сырые PII-идентификаторы пользователя без маскирования,
- содержимое вложений документов.

## Redaction / PII ограничения
Перед логированием обязательны маски:
- Email: `user@example.com` → `u***@example.com`
- Телефоны: маскировать средние цифры (`+7******1234`)
- Секреты/токены: оставлять только префикс и 4 последних символа (`abcd...9f2a`)
- Длинные числовые ID (`>=8` цифр): показывать только последние 2 цифры (`******42`)

## Retention
- Raw payload в постоянное хранилище не записывается в MVP.
- В runtime допустимы только краткоживущие in-memory структуры для обработки запроса.
