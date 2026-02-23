from __future__ import annotations

from datetime import datetime, timezone
import json
import os


def log_report_event(action_id: str, file_id: str, outcome: str) -> None:
    path = os.getenv("MITRA_AUDIT_LOG", "audit/events.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_id": action_id,
        "file_id": file_id,
        "outcome": outcome,
    }

    with open(path, "a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")
