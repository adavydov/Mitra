from __future__ import annotations

from mitra_app.core.policy_engine import Decision


def format_status(*, autonomy_level: str, risk: str, budget: int, capabilities: dict[str, bool]) -> str:
    enabled = ", ".join(k for k, v in capabilities.items() if v) or "none"
    return f"AL={autonomy_level}; Risk={risk}; BudgetDaily={budget}; Capabilities={enabled}"


def format_result(decision: Decision, text: str) -> str:
    if not decision.allow:
        return f"Denied: {decision.reason}"
    return text
