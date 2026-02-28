from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable


_AL_ORDER = ["AL0", "AL1", "AL2", "AL3", "AL4"]
_RISK_ORDER = ["R0", "R1", "R2", "R3", "R4"]
_DEFAULT_RESTRICTED_SCOPE = ("governance/*", ".github/workflows/*", "policy/*")
_DEFAULT_OVERRIDE_LABELS = ("sovereign-override", "l0-approved")


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
                reason=_required_gate_message(policy),
            )

        current_level_cfg = (self._autonomy.get("levels") or {}).get(current_al, {})
        max_risk = str(current_level_cfg.get("max_risk", "R0"))
        if self._risk_index(policy.risk_level) > self._risk_index(max_risk):
            return EnforcementDecision(
                allowed=False,
                reason=_required_gate_message(policy),
            )

        category_limits = self._budget.get("category_limits", {})
        category_limit = category_limits.get(policy.budget_category)
        if category_limit is not None and int(category_limit) <= 0:
            return EnforcementDecision(
                allowed=False,
                reason=_required_gate_message(policy),
            )

        return EnforcementDecision(allowed=True)

    def enforce_file_scope(
        self,
        *,
        changed_paths: Iterable[str],
        allowed_scope: Iterable[str],
        labels: Iterable[str] | None = None,
    ) -> EnforcementDecision:
        scope_patterns = tuple(pattern.strip() for pattern in allowed_scope if pattern and pattern.strip())
        changed = tuple(path.strip() for path in changed_paths if path and path.strip())
        normalized_labels = {str(label).strip().lower() for label in (labels or []) if str(label).strip()}

        for changed_path in changed:
            if any(fnmatch(changed_path, pattern) for pattern in _DEFAULT_RESTRICTED_SCOPE):
                if normalized_labels.intersection(_DEFAULT_OVERRIDE_LABELS):
                    continue
                return EnforcementDecision(
                    allowed=False,
                    reason=f"Denied: restricted scope requires override ({changed_path})",
                )

            if scope_patterns and not any(fnmatch(changed_path, pattern) for pattern in scope_patterns):
                return EnforcementDecision(
                    allowed=False,
                    reason=f"Denied: path out of allowed scope ({changed_path})",
                )

        return EnforcementDecision(allowed=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

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


def _required_gate_message(policy: CommandPolicy) -> str:
    return f"Denied: requires {policy.required_al}/{policy.risk_level}"
