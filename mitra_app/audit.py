from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

AUDIT_PATH = Path("audit/audit.jsonl")
REDACTED = "[REDACTED]"
SENSITIVE_ENV_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if "key" in key.lower() else _redact(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_redact(item) for item in value]

    if isinstance(value, str):
        redacted = value
        for env_var in SENSITIVE_ENV_VARS:
            secret_value = os.getenv(env_var)
            if secret_value:
                redacted = redacted.replace(secret_value, REDACTED)
        return redacted

    return value


def log_event(event: dict) -> str:
    safe_event = _redact(event)
    line = json.dumps(safe_event, ensure_ascii=False)

    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")

    print(line, flush=True)
    return line
