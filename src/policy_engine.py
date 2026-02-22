"""Mitra policy engine.

Mandatory gate: evaluate(AL, Risk, Budget, ToolPermission) before every action.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable


RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class Decision:
    allowed: bool
    reasons: list[str]
    quarantine_triggered: bool = False


class PolicyEngine:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.autonomy = self._read_json("config/autonomy.json")
        self.risk = self._read_json("config/risk.json")
        self.budget = self._read_json("config/budget.json")

        self.current_al = self.autonomy["current_level"]
        self.current_spend = 0
        self.denied_streak = 0

    def evaluate(self, action: str, declared_risk: str | None = None) -> Decision:
        """Evaluate AL, Risk, Budget and ToolPermission for an action."""
        reasons: list[str] = []

        # AL / ToolPermission
        level = self.autonomy["levels"].get(self.current_al)
        if not level:
            return self._deny([f"Unknown autonomy level: {self.current_al}"], anomaly=True)

        if action not in level["allowed_tools"]:
            reasons.append(f"Tool '{action}' is not allowed for {self.current_al}")

        # Risk
        mapped_risk = self.risk["categories"].get(action, "CRITICAL")
        effective_risk = self._max_risk(mapped_risk, declared_risk or mapped_risk)
        if self._risk_index(effective_risk) > self._risk_index(level["max_risk"]):
            reasons.append(
                f"Risk '{effective_risk}' exceeds {self.current_al} max risk '{level['max_risk']}'"
            )

        # Budget
        tool_cost = self.budget["tool_costs"].get(action)
        if tool_cost is None:
            reasons.append(f"No budget cost configured for tool '{action}'")
        else:
            if tool_cost > level["max_budget_per_action"]:
                reasons.append(
                    f"Tool cost {tool_cost} exceeds {self.current_al} per-action max "
                    f"{level['max_budget_per_action']}"
                )
            if self.current_spend + tool_cost > self.budget["hard_limit"]:
                reasons.append("Projected spend exceeds hard limit")

        if reasons:
            self.denied_streak += 1
            anomaly = self.denied_streak >= 3
            return self._deny(reasons, anomaly=anomaly)

        self.denied_streak = 0
        return Decision(allowed=True, reasons=["Allowed"])

    def guarded_action(
        self,
        action: str,
        handler: Callable[..., Any],
        *args: Any,
        declared_risk: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run an action only if policy evaluation allows it."""
        decision = self.evaluate(action=action, declared_risk=declared_risk)
        if not decision.allowed:
            raise PermissionError("; ".join(decision.reasons))

        result = handler(*args, **kwargs)
        self.current_spend += self.budget["tool_costs"][action]
        return result

    def report_anomaly(self, anomaly_type: str) -> Decision:
        """External anomaly hook. Any listed anomaly forces AL0 quarantine."""
        if anomaly_type in self.risk.get("anomaly_triggers", []):
            return self._deny([f"Anomaly detected: {anomaly_type}"], anomaly=True)
        return Decision(allowed=True, reasons=["No anomaly action required"])

    def _deny(self, reasons: list[str], anomaly: bool = False) -> Decision:
        if anomaly:
            self.current_al = "AL0"
            reasons.append("Quarantine fallback activated: autonomy downgraded to AL0")
        return Decision(allowed=False, reasons=reasons, quarantine_triggered=anomaly)

    def _read_json(self, relpath: str) -> dict[str, Any]:
        with (self.root / relpath).open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _risk_index(risk: str) -> int:
        if risk not in RISK_ORDER:
            return len(RISK_ORDER) - 1
        return RISK_ORDER.index(risk)

    def _max_risk(self, left: str, right: str) -> str:
        return left if self._risk_index(left) >= self._risk_index(right) else right
