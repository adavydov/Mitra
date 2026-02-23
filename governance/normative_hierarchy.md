ID: L0-HIER-01
Level: L0
Owner: User
Status: active
Depends on: L0-CONST

# Нормативная иерархия Митры (v0)

## 1) Уровни и приоритеты
- L0: Конституция.
- L1: Идентичность + доменные кодексы.
- L2: Политики + протоколы.
- L3: Ранбуки + конфиг.

### Meta-слои
- H: Capabilities.
- I: Evidence.
- J: Evals/Tests.

## 2) Конфликт-резолвер
Порядок приоритета: `L0 > L1 > L2(Policy) > L2(Protocol) > L3(Runbook) > L3(Config)`.
- Config не расширяет права policy.
- Runbook не меняет смысл policy/protocol.
- Неизвестный случай: безопаснее/обратимее, лог в аудит, PR-предложение.

## 3) Дерево документов A–J
- A: governance/constitution.md
- B: governance/identity.md + governance/codex/*
- C: policy/*
- D: protocols/*
- E: runbooks/*
- F: config/*
- G: capabilities/*
- H: audit/
- I: reports/
- J: evals/*

## 4) Правило одного места истины
- Принцип → Codex
- Порог/решение → Policy
- Алгоритм → Protocol
- Пошаговка → Runbook
- Значение → Config
- Факт выполнения → Audit/Evidence
- Доверие → Evals/Tests

## 5) ID-стиль
- Codex: `C-XXX-01`
- Policy: `P-XXX-01`
- Protocol: `PR-XXX-01`
- Runbook: `RB-XXX-01`
- Config: `CFG-XXX-01`
- Capability: `CAP-XXX-01`
- Eval: `EVAL-XXX-01`

## 6) Шаблон документа
Каждый нормативный markdown содержит: `ID`, `Level`, `Owner`, `Status`, `Depends on`, `Config keys`, `Required evals`.

## 7) GitOps
- `main` — production.
- `proposals/*` — предложения.
- L0/L1: merge только пользователем.
- Policy/Codex: merge только пользователем, evals обязательны.
- Config: агент меняет только в сторону ужесточения.

## 8) CI-gates
- `lint_ids`: шапки, уникальность ID, корректный `Depends on`.
- `validate_config`: JSON + schema.
- `pytest`: regression/security/privacy evals.

## 9) Anti-bloat
- Конституция: только аксиомы и порядок изменений.
- Codex/Policy: без пошаговки.
- Поведенческие изменения разрешены только через нормы + тесты.
