import httpx
import pytest

from mitra_app.llm.anthropic import (
    ANTHROPIC_MESSAGES_URL,
    AnthropicClient,
    DEFAULT_ANTHROPIC_MODEL,
)


def test_create_message_uses_env_defaults_and_headers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("LLM_MAX_TOKENS_OUT", "777")
    monkeypatch.setenv("LLM_TIMEOUT_S", "15")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"id": "msg_1", "content": [{"type": "text", "text": "ok"}]})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    anthropic = AnthropicClient(client=client)

    response = anthropic.create_message([{"role": "user", "content": "hello"}])

    assert response["id"] == "msg_1"
    assert captured["url"] == ANTHROPIC_MESSAGES_URL
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert '"model":"claude-sonnet-4-6"' in captured["json"]
    assert '"max_tokens":777' in captured["json"]


def test_create_message_retries_on_429(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"error": "rate_limited"})
        return httpx.Response(200, json={"id": "msg_ok"})

    anthropic = AnthropicClient(client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=2)

    response = anthropic.create_message([{"role": "user", "content": "retry"}])

    assert response["id"] == "msg_ok"
    assert calls["count"] == 2


def test_create_message_retries_timeout_and_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out")

    anthropic = AnthropicClient(client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=1)

    with pytest.raises(httpx.ReadTimeout):
        anthropic.create_message([{"role": "user", "content": "timeout"}])

    assert calls["count"] == 2


def test_raises_if_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    anthropic = AnthropicClient(model=DEFAULT_ANTHROPIC_MODEL)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        anthropic.create_message([{"role": "user", "content": "hello"}])


class _RecordingClient:
    def __init__(self):
        self.last_timeout = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.last_timeout = timeout
        request = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(200, json={"id": "msg_2"}, request=request)


def test_timeout_env_used_for_injected_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_S", "42")

    recording_client = _RecordingClient()
    anthropic = AnthropicClient(client=recording_client)

    anthropic.create_message([{"role": "user", "content": "hello"}])

    assert recording_client.last_timeout == 42.0
