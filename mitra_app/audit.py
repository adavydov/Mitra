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


def log_report_event(
    action_id: str,
    file_id: str,
    outcome: str,
    user_id: int | None = None,
    chat_id: int | None = None,
    link: str | None = None,
    telegram_update_id: int | None = None,
    action_type: str = "/report",
    log_level: str = "info",
) -> None:
    try:
        event: dict[str, object] = {
            "action_id": action_id,
            "telegram_update_id": telegram_update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "action_type": action_type,
            "file_id": file_id,
            "outcome": outcome,
            "log_level": log_level,
        }
        if link:
            event["link"] = link
        log_event(event)
    except Exception as exc:
        print(
            {
                "event": "log_report_event_failed",
                "action_id": action_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "file_id": file_id,
                "outcome": outcome,
                "link": link,
                "telegram_update_id": telegram_update_id,
                "action_type": action_type,
                "log_level": "error",
                "error": str(exc),
            }
        )
