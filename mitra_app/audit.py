from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


def log_report_event(action_id: str, file_id: str, outcome: str, link: str | None = None) -> None:
    path = os.getenv("MITRA_AUDIT_LOG", "audit/events.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)

        redacted = value
        for secret in known_secret_values:
            redacted = redacted.replace(secret, REDACTED)
        return redacted

    return value


def log_event(event: dict) -> str:
    """Append an audit event as JSONL and print a compact line to stdout."""
    known_secret_values = _collect_secret_values()

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    if link:
        event["link"] = link

    line = json.dumps(redacted_payload, ensure_ascii=False, separators=(",", ":"))
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as audit_file:
        audit_file.write(line + "\n")

    print(line)
    return line


def log_report_event(action_id: str, file_id: str, outcome: str) -> None:
    log_event({"action_id": action_id, "file_id": file_id, "outcome": outcome})
