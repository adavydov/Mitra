from __future__ import annotations

from datetime import datetime, timezone
import json
import os


def log_event(event: dict[str, object]) -> None:
    path = os.getenv("MITRA_AUDIT_LOG", "audit/events.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }

    with open(path, "a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def log_report_event(action_id: str, file_id: str, outcome: str, link: str | None = None) -> None:
    event = {
        "action_id": action_id,
        "user_id": user_id,
        "file_id": file_id,
        "outcome": outcome,
    }
    if link:
        event["link"] = link
    log_event(event)
