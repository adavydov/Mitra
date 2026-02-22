# Протокол внешних запросов

## Цель
Стандартизировать вызовы внешних сервисов (LLM/Drive/Telegram) при формировании исследовательского отчёта.

## Общий контракт
Каждый внешний вызов проходит этапы:
1. `prepare` — сбор параметров и корреляционного `request_id`.
2. `execute` — сетевой запрос с таймаутом и ретраями.
3. `validate` — проверка обязательных полей ответа.
4. `emit` — запись события в журнал выполнения.

## Подпроцесс: создание документа/отчёта (`external.report.create`)

### Вход
- `task_id`: строка идентификатора задачи.
- `topic`: тема отчёта.
- `findings`: список тезисов/фактов.
- `audience`: целевая аудитория.

### Шаги
1. **Сформировать текст отчёта**
   - Результат: `report_text` (markdown/plain).
2. **Создать файл в Drive**
   - MIME: `text/markdown` (или `application/vnd.google-apps.document` при конвертации).
   - Результат: `file_id`.
3. **Настроить доступ по ссылке**
   - Permission: `type=anyone`, `role=reader` (если разрешено политикой).
4. **Получить shareable link**
   - Читать `webViewLink`.

### Выход
```json
{
  "task_id": "...",
  "file_id": "...",
  "shareable_link": "https://drive.google.com/...",
  "status": "completed"
}
```

### Ошибки
- `auth_failed`: токен истёк/отозван.
- `quota_exceeded`: превышена квота Drive API.
- `permission_denied`: запрет на создание публичной ссылки.
- `transient_network_error`: временная сетевая ошибка (разрешены ретраи).
