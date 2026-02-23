from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


AUDIT_PATH = Path("audit/audit.jsonl")
REDACTED = "[REDACTED]"
SENSITIVE_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "DRIVE_SERVICE_ACCOUNT_JSON",
    "DRIVE_SERVICE_ACCOUNT_JSON_B64",
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|api[_-]?key|private[_-]?key|credential)", re.IGNORECASE
)


def _collect_secret_values() -> list[str]:
    import os

    values: list[str] = []
    for key in SENSITIVE_ENV_KEYS:
        value = os.getenv(key)
        if value:
            values.append(value)
    return sorted(values, key=len, reverse=True)


def _redact_value(value: Any, known_secret_values: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if SENSITIVE_KEY_PATTERN.search(k) else _redact_value(v, known_secret_values))
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [_redact_value(item, known_secret_values) for item in value]

    if isinstance(value, str):
        if "-----BEGIN" in value:
            return REDACTED

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
    redacted_payload = _redact_value(payload, known_secret_values)

    line = json.dumps(redacted_payload, ensure_ascii=False, separators=(",", ":"))
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as audit_file:
        audit_file.write(line + "\n")

    print(line)
    return line


def log_report_event(action_id: str, file_id: str, outcome: str) -> None:
    log_event({"action_id": action_id, "file_id": file_id, "outcome": outcome})
