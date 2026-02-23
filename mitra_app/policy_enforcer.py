from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_AL_ORDER = ["AL0", "AL1", "AL2", "AL3", "AL4"]
_RISK_ORDER = ["R0", "R1", "R2", "R3", "R4"]


@dataclass(frozen=True)
class CommandPolicy:
    required_al: str
    risk_level: str
    budget_category: str


@dataclass(frozen=True)
class EnforcementDecision:
    allowed: bool
    reason: str | None = None


class CommandPolicyEnforcer:
    def __init__(self, root: Path | str) -> None:
        repo_root = Path(root)
        self._autonomy = self._read_json(repo_root / "config" / "autonomy.json")
        self._risk = self._read_json(repo_root / "config" / "risk.json")
        self._budget = self._read_json(repo_root / "config" / "budget.json")

    def enforce(self, *, current_al: str, policy: CommandPolicy) -> EnforcementDecision:
        if self._al_index(current_al) < self._al_index(policy.required_al):
            return EnforcementDecision(
                allowed=False,
                reason=f"Denied: requires {policy.required_al} (current {current_al})",
            )

        current_level_cfg = (self._autonomy.get("levels") or {}).get(current_al, {})
        max_risk = str(current_level_cfg.get("max_risk", "R0"))
        if self._risk_index(policy.risk_level) > self._risk_index(max_risk):
            return EnforcementDecision(
                allowed=False,
                reason=f"Denied: risk {policy.risk_level} exceeds max {max_risk} for {current_al}",
            )

        category_limits = self._budget.get("category_limits", {})
        category_limit = category_limits.get(policy.budget_category)
        if category_limit is not None and int(category_limit) <= 0:
            return EnforcementDecision(
                allowed=False,
                reason=f"Denied: budget for {policy.budget_category} is exhausted",
            )

        return EnforcementDecision(allowed=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _al_index(level: str) -> int:
        try:
            return _AL_ORDER.index(level)
        except ValueError:
            return -1

    @staticmethod
    def _risk_index(level: str) -> int:
        try:
            return _RISK_ORDER.index(level)
        except ValueError:
            return len(_RISK_ORDER)
