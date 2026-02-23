import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from mitra_app.telegram import send_message

app = FastAPI()


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

    if text.startswith("/status"):
        reply_text = "Mitra alive"
    elif text.startswith("/help") or text.startswith("/start"):
        reply_text = "Commands: /status"
    else:
        reply_text = "Unknown command"

    if chat_id is not None:
        await send_message(chat_id=chat_id, text=reply_text)

    return {"status": "ok"}
