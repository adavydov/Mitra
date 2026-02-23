import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
    payload = {"chat_id": chat_id, "text": text}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(api_url, json=payload)
        response.raise_for_status()

    return True
