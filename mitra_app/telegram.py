import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str) -> bool:
    """Send a message via the Telegram Bot API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; skipping Telegram send")
        return True

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("telegram_send_message_http_error", extra={"chat_id": chat_id})
        return False

    return True
