from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mitra_app.telegram import ensure_webhook


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeAsyncClient:
    def __init__(self, *args: Any, **kwargs: Any):
        self._get_handler: Callable[[str], FakeResponse] | None = kwargs.pop("_get_handler", None)
        self._post_handler: Callable[[str, dict[str, Any]], FakeResponse] | None = kwargs.pop("_post_handler", None)

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> FakeResponse:
        assert self._get_handler is not None
        return self._get_handler(url)

    async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        assert self._post_handler is not None
        return self._post_handler(url, json)


def test_ensure_webhook_calls_set_when_url_mismatch(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_get(url: str) -> FakeResponse:
        assert url.endswith("/getWebhookInfo")
        return FakeResponse({"ok": True, "result": {"url": ""}})

    def fake_post(url: str, payload: dict[str, Any]) -> FakeResponse:
        calls.append((url, payload))
        return FakeResponse({"ok": True, "result": True})

    monkeypatch.setattr(
        "mitra_app.telegram.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, _post_handler=fake_post, **kwargs),
    )

    ok, detail = __import__("asyncio").run(ensure_webhook())

    assert ok is True
    assert detail == "ok"
    assert len(calls) == 1
    assert calls[0][0].endswith("/setWebhook")
    assert calls[0][1] == {
        "url": "https://example.com/telegram/webhook",
        "secret_token": "secret",
        "allowed_updates": ["message"],
    }


def test_ensure_webhook_does_not_call_set_when_url_matches(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com/")

    post_calls: list[tuple[str, dict[str, Any]]] = []

    def fake_get(url: str) -> FakeResponse:
        assert url.endswith("/getWebhookInfo")
        return FakeResponse({"ok": True, "result": {"url": "https://example.com/telegram/webhook"}})

    def fake_post(url: str, payload: dict[str, Any]) -> FakeResponse:
        post_calls.append((url, payload))
        return FakeResponse({"ok": True, "result": True})

    monkeypatch.setattr(
        "mitra_app.telegram.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, _post_handler=fake_post, **kwargs),
    )

    ok, detail = __import__("asyncio").run(ensure_webhook())

    assert ok is True
    assert detail == "ok"
    assert post_calls == []
