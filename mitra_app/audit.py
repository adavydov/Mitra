from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re


_SENSITIVE_KEY_RE = re.compile(r"(token|secret|password|private|api[_-]?key|access[_-]?key)", re.IGNORECASE)
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)
_CREDENTIAL_LIKE_RE = re.compile(
    r"(" 
    r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9._-]{10,}\.[a-zA-Z0-9._-]{10,}"  # JWT
    r"|gh[pousr]_[A-Za-z0-9]{20,}"  # GitHub-like tokens
    r"|(?=[A-Za-z0-9+/_-]{32,})(?=.*[A-Za-z])(?=.*\\d)[A-Za-z0-9+/_-]{32,}"  # long mixed credential-like strings
    r")"
)


def _sensitive_values() -> set[str]:
    names = {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "DRIVE_SERVICE_ACCOUNT_JSON",
        "DRIVE_SERVICE_ACCOUNT_JSON_B64",
        "DRIVE_OAUTH_CLIENT_SECRET",
        "DRIVE_OAUTH_REFRESH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "BRAVE_SEARCH_API_KEY",
    }
    values: set[str] = set()
    for name in names:
        value = os.getenv(name)
        if value:
            values.add(value)
    return values


def _redact_value(value: object, *, key: str | None = None) -> object:
    if isinstance(value, dict):
        return {k: _redact_value(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, key=key) for item in value)

    key_is_sensitive = bool(key and _SENSITIVE_KEY_RE.search(key))
    if key_is_sensitive:
        return "[REDACTED]"

    if isinstance(value, str):
        if _PEM_RE.search(value):
            return "[REDACTED]"

        redacted = value
        for sensitive in _sensitive_values():
            if sensitive and sensitive in redacted:
                redacted = redacted.replace(sensitive, "[REDACTED]")
        redacted = _CREDENTIAL_LIKE_RE.sub("[REDACTED]", redacted)
        return redacted

    return value


def log_event(event: dict[str, object]) -> str:
    path = os.getenv("MITRA_AUDIT_LOG", "audit/events.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **_redact_value(event),
    }
    line = json.dumps(payload, ensure_ascii=False)

    with open(path, "a", encoding="utf-8") as audit_file:
        audit_file.write(line + "\n")

    print(line)
    return line


def log_budget_usage(category: str, amount: int = 1, metadata: dict[str, object] | None = None) -> None:
    path = os.getenv("MITRA_BUDGET_LEDGER", "audit/budget_ledger.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "amount": amount,
    }
    if metadata:
        payload["metadata"] = metadata

    with open(path, "a", encoding="utf-8") as ledger_file:
        ledger_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
