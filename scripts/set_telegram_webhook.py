#!/usr/bin/env python3
from __future__ import annotations

import os
import urllib.parse
import urllib.request


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not token or not webhook_url:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_URL")
        return 1
    endpoint = f"https://api.telegram.org/bot{token}/setWebhook"
    data = urllib.parse.urlencode({"url": webhook_url, "secret_token": secret}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(resp.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
