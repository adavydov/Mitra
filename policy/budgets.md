# Budget Policy

## Budget Controls
- Budget is tracked in `tokens` on a daily window.
- `soft_limit`: planning warning threshold.
- `hard_limit`: strict deny threshold.
- Per-action max budget is additionally constrained by autonomy level.

## Enforcement Rules
Before every action:
1. Resolve tool cost from `config/budget.json`.
2. Deny if tool cost is undefined (deny-by-default).
3. Deny if projected spend exceeds hard limit.
4. Deny if cost exceeds current AL per-action max.

When soft limit is crossed, emit warning but allow actions if all hard constraints pass.
