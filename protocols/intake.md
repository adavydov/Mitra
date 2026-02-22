# PR-INTAKE-01 — Протокол intake

## Назначение
Протокол intake определяет, как входящий запрос из Telegram webhook преобразуется в нормализованную задачу для runtime перед любыми действиями.

## Входы
- `update_id`: идентификатор Telegram update.
- `message`/`edited_message`:
  - `text` или `caption` (основной вход для классификации).
  - `chat.id`, `from.id`, `date`.
- `document` (опционально): метаданные вложения (`file_name`, `mime_type`, `file_size`).
- Контекст исполнения:
  - `AUTONOMY_LEVEL` (`low|medium|high`).
  - `RISK_APPETITE` (`low|medium|high`).

## Выходы
Нормализованный объект intake:
- `request_id`: `tg:<update_id>`.
- `source`: `telegram`.
- `raw_text`: текст для анализа (из `text` или `caption`).
- `classification`:
  - `report_document_request`
  - `unknown`
  - `restricted`
- `decision`:
  - `allow` — допускается дальнейшая обработка.
  - `block` — запрос отклонён политикой.
- `reason`: объяснение решения (`policy_gate_passed`, `restricted_content`, `autonomy_too_low`, `risk_appetite_too_low`).

## Алгоритм классификации
1. **Извлечение текста**: взять `message.text`, иначе `message.caption`, иначе пустую строку.
2. **Нормализация**: привести к нижнему регистру, удалить лишние пробелы.
3. **Проверка restricted-признаков (приоритет 1)**:
   - команды на взлом, malware, обход ограничений, кражу данных/PII.
   - если найден признак, класс = `restricted`.
4. **Проверка report/document request (приоритет 2)**:
   - намерение «подготовь/сделай/создай отчёт|документ|справку|резюме|pdf|doc».
   - если найдено, класс = `report_document_request`.
5. **Fallback**:
   - класс = `unknown`.
6. **Policy gating**:
   - класс маппится на минимальные требования `Autonomy Level` и `Risk Appetite`.
   - если текущие уровни ниже требований, `decision=block`.

## Примечания
- `restricted` всегда блокируется независимо от уровней автономии/риска.
- Классификация rule-based (MVP) и должна сопровождаться eval-наборами для регрессии.
