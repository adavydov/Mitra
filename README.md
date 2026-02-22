# Mitra
Митра — симбиотический аватар Пользователя в цифровом мире: действует как продолжение воли Пользователя. Митра существует только в паре с Пользователем.

## Governance baseline
В репозитории добавлены:
- `config/*.json` — параметры автономности, риска и бюджетов.
- `schemas/*.schema.json` — JSON Schema для валидации конфигов.
- `governance/codex/*.md` и `policy/*.md` — нормативные правила.
- `src/policy_engine.py` — policy engine с обязательной проверкой
  `evaluate(AL, Risk, Budget, ToolPermission)` перед каждым действием,
  deny-by-default и quarantine fallback в `AL0`.
