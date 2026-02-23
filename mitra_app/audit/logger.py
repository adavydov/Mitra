from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("mitra.audit")


def _mask_secret(text: str) -> str:
    return text[:4] + "..." + text[-2:] if len(text) > 8 else "[redacted]"


def redact_text(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    safe = ''.join('*' if ch.isdigit() else ch for ch in text)
    snippet = safe[:80]
    return f"snippet={snippet!r};sha256={digest}"


def log_event(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat()
    if "message_text" in event:
        event["message_text"] = redact_text(event["message_text"])
    for key in list(event.keys()):
        if "secret" in key.lower() or "token" in key.lower():
            event[key] = _mask_secret(str(event[key]))
    logger.info(json.dumps(event, ensure_ascii=False))
