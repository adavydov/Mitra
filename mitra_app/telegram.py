import os

import httpx


async def send_message(chat_id: int, text: str) -> None:
    """Send a message via the Telegram Bot API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(api_url, json=payload)
        response.raise_for_status()
