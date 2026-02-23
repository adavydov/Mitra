import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException

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


def _audit_allowlist_denied(user_id: int | None, chat_id: int | None) -> None:
    logger.info(
        "telegram_allowlist_denied",
        extra={
            "event": "telegram_allowlist_denied",
            "user_id": user_id,
            "chat_id": chat_id,
        },
    )


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

    allowed_user_ids = _load_allowed_user_ids()
    if allowed_user_ids and user_id not in allowed_user_ids:
        _audit_allowlist_denied(user_id=user_id, chat_id=chat_id)
        return {"status": "ok"}

    if text.startswith("/status"):
        reply_text = "Mitra alive"
    elif text.startswith("/whoami"):
        reply_text = f"user_id={user_id}, chat_id={chat_id}"
    elif text.startswith("/help") or text.startswith("/start"):
        reply_text = "Commands: /status, /whoami"
    else:
        reply_text = "Unknown command"

    if chat_id is not None:
        await send_message(chat_id=chat_id, text=reply_text)

    return {"status": "ok"}
