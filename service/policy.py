"""Policy layer for webhook processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def evaluate(event: Dict[str, Any], shared_secret: str | None) -> PolicyDecision:
    """Validate minimum policy requirements before task execution."""
    if not shared_secret:
        return PolicyDecision(False, "SERVICE_SHARED_SECRET is not configured")

    provided = event.get("secret")
    if provided != shared_secret:
        return PolicyDecision(False, "invalid secret")

    event_type = event.get("type")
    if event_type not in {"sync", "reconcile", "noop"}:
        return PolicyDecision(False, "unsupported event type")

    return PolicyDecision(True, "accepted")
