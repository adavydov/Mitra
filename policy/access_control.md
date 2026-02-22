# Access Control Policy

## Допустимые классы входов из Telegram
- `report_document_request`: допустим к обработке при прохождении policy gate.
- `unknown`: допустим только в режиме безопасного ответа (без внешних действий).
- `restricted`: запрещён; выполнение действий блокируется.

## Матрица допуска
| Класс | Минимальный Autonomy Level | Минимальный Risk Appetite | Действие |
|---|---|---|---|
| report_document_request | medium | medium | allow при соответствии обоим условиям |
| unknown | low | low | allow (safe-mode only) |
| restricted | high | high | всегда block |

## Правила исполнения
1. Каждый входящий webhook проходит `classification` до запуска обработчиков.
2. Затем применяется проверка `Autonomy Level` и `Risk Appetite`.
3. При несоответствии уровней — `block` с причиной:
   - `autonomy_too_low`
   - `risk_appetite_too_low`
4. Для `unknown` запрещены побочные эффекты (изменение внешних систем).
