from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    allow: bool
    reason: str


def enforce(*, classification: str, user_id: int, allowed_user_ids: set[int], autonomy_level: str) -> Decision:
    if allowed_user_ids and user_id not in allowed_user_ids:
        return Decision(False, "user_not_allowlisted")
    if classification == "restricted":
        return Decision(False, "restricted_content")
    if autonomy_level == "AL0" and classification != "status_request":
        return Decision(False, "safe_mode_al0")
    return Decision(True, "allowed")
