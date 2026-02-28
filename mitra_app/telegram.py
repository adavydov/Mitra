import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_TEXT_LIMIT = 4096


def _build_expected_webhook_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/telegram/webhook"


async def ensure_webhook() -> tuple[bool, str]:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    public_base_url = os.getenv("PUBLIC_BASE_URL")

    if not bot_token or not secret:
        logger.info("Skipping webhook sync: missing token or secret")
        return True, "skipped: missing TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET"

    if not public_base_url:
        logger.info("Skipping webhook sync: missing PUBLIC_BASE_URL")
        return True, "skipped: missing PUBLIC_BASE_URL"

    expected_url = _build_expected_webhook_url(public_base_url)
    base_api_url = f"https://api.telegram.org/bot{bot_token}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            get_response = await client.get(f"{base_api_url}/getWebhookInfo")
            get_response.raise_for_status()
            get_payload: dict[str, Any] = get_response.json()
            current_url = (get_payload.get("result") or {}).get("url", "")

            if current_url == expected_url:
                return True, "ok"

            payload = {
                "url": expected_url,
                "secret_token": secret,
                "allowed_updates": ["message"],
            }
            set_response = await client.post(f"{base_api_url}/setWebhook", json=payload)
            set_response.raise_for_status()
            set_payload: dict[str, Any] = set_response.json()
            if not set_payload.get("ok"):
                description = str(set_payload.get("description", "setWebhook returned ok=false"))
                logger.warning("setWebhook failed", extra={"description": description})
                return False, description

        return True, "ok"
    except Exception as exc:
        logger.exception("webhook_sync_failed")
        return False, str(exc)


async def send_message(chat_id: int, text: str) -> bool:
    """Send a message via the Telegram Bot API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; skipping Telegram send")
        return True

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    sanitized_text = sanitize_telegram_text(text)
    if not sanitized_text:
        logger.info("telegram_send_message_skipped_empty", extra={"chat_id": chat_id})
        return True

    chunks = chunk_telegram_message(sanitized_text, limit=_TELEGRAM_TEXT_LIMIT)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for chunk in chunks:
                payload = {"chat_id": chat_id, "text": chunk}
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("telegram_send_message_http_error", extra={"chat_id": chat_id})
        return False

    return True


def sanitize_telegram_text(text: str) -> str:
    sanitized = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.IGNORECASE | re.DOTALL)
    sanitized = re.sub(r"</?thinking>", "", sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


def chunk_telegram_message(text: str, limit: int = _TELEGRAM_TEXT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    start = 0
    total_len = len(text)
    while start < total_len:
        end = min(start + limit, total_len)
        if end == total_len:
            chunks.append(text[start:end])
            break

        split_at = max(text.rfind("\n", start, end + 1), text.rfind(" ", start, end + 1))
        if split_at <= start:
            split_at = end

        chunk = text[start:split_at].rstrip()
        if not chunk:
            chunk = text[start:end]
            split_at = end
        chunks.append(chunk)

        start = split_at
        while start < total_len and text[start].isspace():
            start += 1

    return chunks
