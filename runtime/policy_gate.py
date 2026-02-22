"""Policy checks for autonomy/risk gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Classification = Literal["report_document_request", "unknown", "restricted"]
Decision = Literal["allow", "block"]

LEVEL_ORDER = {"low": 1, "medium": 2, "high": 3}

REQUIREMENTS = {
    "report_document_request": {"autonomy": "medium", "risk": "medium"},
    "unknown": {"autonomy": "low", "risk": "low"},
    "restricted": {"autonomy": "high", "risk": "high"},
}


@dataclass
class GateResult:
    decision: Decision
    reason: str


def _at_least(current: str, needed: str) -> bool:
    return LEVEL_ORDER.get(current, 0) >= LEVEL_ORDER[needed]


def apply_policy_gate(classification: Classification, autonomy_level: str, risk_appetite: str) -> GateResult:
    if classification == "restricted":
        return GateResult(decision="block", reason="restricted_content")

    needed = REQUIREMENTS[classification]

    if not _at_least(autonomy_level, needed["autonomy"]):
        return GateResult(decision="block", reason="autonomy_too_low")

    if not _at_least(risk_appetite, needed["risk"]):
        return GateResult(decision="block", reason="risk_appetite_too_low")

    return GateResult(decision="allow", reason="policy_gate_passed")
