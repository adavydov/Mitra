import asyncio
from collections.abc import Callable
from typing import Any

from mitra_app.telegram import sanitize_telegram_text, send_message


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    def __init__(self, *args: Any, **kwargs: Any):
        self._post_handler: Callable[[str, dict[str, Any]], FakeResponse] | None = kwargs.pop("_post_handler", None)

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        assert self._post_handler is not None
        return self._post_handler(url, json)


def test_strip_thinking_block():
    text = "before\n<thinking>internal reasoning</thinking>\nafter"
    cleaned = sanitize_telegram_text(text)
    assert "<thinking>" not in cleaned
    assert "before" in cleaned
    assert "after" in cleaned


def test_preserve_normal_angle_brackets():
    text = "Use <b>bold</b> and 2 < 3"
    assert sanitize_telegram_text(text) == "Use <b>bold</b> and 2 < 3"


def test_chunking_after_sanitize(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")

    sent_payloads: list[dict[str, Any]] = []

    def fake_post(url: str, payload: dict[str, Any]) -> FakeResponse:
        sent_payloads.append(payload)
        return FakeResponse()

    monkeypatch.setattr(
        "mitra_app.telegram.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _post_handler=fake_post, **kwargs),
    )

    long_text = "<thinking>hidden</thinking>" + ("я" * 5000)

    ok = asyncio.run(send_message(chat_id=123, text=long_text))

    assert ok is True
    assert len(sent_payloads) == 2
    assert all("<thinking>" not in payload["text"] for payload in sent_payloads)
    assert "".join(payload["text"] for payload in sent_payloads) == ("я" * 5000)
