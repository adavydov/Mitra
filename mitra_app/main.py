import logging
import os
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from mitra_app.audit import log_report_event
from mitra_app.drive import DriveNotConfiguredError, upload_markdown_document
from mitra_app.telegram import send_message

app = FastAPI()
logger = logging.getLogger(__name__)


def _load_allowed_user_ids() -> set[int]:
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
    allowed: set[int] = set()

    for value in raw.split(","):
        stripped = value.strip()
        if not stripped:
            continue
        try:
            allowed.add(int(stripped))
        except ValueError:
            logger.warning("Ignoring invalid ALLOWED_TELEGRAM_USER_IDS value", extra={"value": stripped})

    return allowed


def _is_allowlist_configured(raw_value: str | None) -> bool:
    return bool(raw_value and raw_value.strip())


def _audit_allowlist_denied(user_id: int | None, chat_id: int | None) -> None:
    logger.info(
        "telegram_allowlist_denied",
        extra={
            "event": "telegram_allowlist_denied",
            "user_id": user_id,
            "chat_id": chat_id,
        },
    )


def _slugify(text: str, max_len: int = 24) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:max_len] or "report"


def _build_report_title(text: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    return f"report-{stamp}-{_slugify(text)}"


def _build_report_body(text: str, now: datetime) -> str:
    timestamp = now.isoformat()
    return f"{text.strip()}\n\n---\ntimestamp: {timestamp}\n"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret or x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    message = update.get("message") or {}
    text = message.get("text", "")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    from_user = message.get("from") or {}
    user_id = from_user.get("id")

    allowed_user_ids_raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS")
    allowed_user_ids = _load_allowed_user_ids()
    allowlist_configured = _is_allowlist_configured(allowed_user_ids_raw)

    if allowlist_configured and user_id not in allowed_user_ids:
        _audit_allowlist_denied(user_id=user_id, chat_id=chat_id)
        return {"status": "ok"}

    if text.startswith("/status"):
        reply_text = "Mitra alive"
    elif text.startswith("/whoami"):
        reply_text = f"user_id={user_id}, chat_id={chat_id}"
    elif not allowlist_configured:
        reply_text = "Allowlist not configured. Set ALLOWED_TELEGRAM_USER_IDS."
    elif text.startswith("/report"):
        report_text = text[len("/report") :].strip()
        action_id = f"act-{uuid4().hex[:12]}"
        file_id = ""

        if not report_text:
            reply_text = "Usage: /report <text>"
            log_report_event(action_id=action_id, file_id=file_id, outcome="invalid")
        else:
            now = datetime.now(timezone.utc)
            title = _build_report_title(report_text, now)
            body = _build_report_body(report_text, now)

            try:
                upload = await upload_markdown_document(title=title, markdown_body=body)
                file_id = upload.file_id
                link = upload.web_view_link or upload.file_id
                reply_text = f"Report uploaded: {link}"
                log_report_event(action_id=action_id, file_id=file_id, outcome="success")
            except DriveNotConfiguredError:
                reply_text = "Drive disabled"
                log_report_event(action_id=action_id, file_id=file_id, outcome="drive_disabled")
            except Exception:
                reply_text = "Report failed"
                log_report_event(action_id=action_id, file_id=file_id, outcome="error")
    elif text.startswith("/help") or text.startswith("/start"):
        reply_text = "Commands: /status, /report <text>"
    else:
        reply_text = "Unknown command"

    if chat_id is not None:
        await send_message(chat_id=chat_id, text=reply_text)

    return {"status": "ok"}
