import os
from typing import Any

import httpx

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS_OUT = 600
DEFAULT_TIMEOUT_S = 30


class AnthropicClient:
    """Minimal client for Anthropic Messages API with retry support."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens_out: int | None = None,
        timeout_s: float | None = None,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        self.max_tokens_out = max_tokens_out if max_tokens_out is not None else _env_int(
            "LLM_MAX_TOKENS_OUT", DEFAULT_MAX_TOKENS_OUT
        )
        self.timeout_s = timeout_s if timeout_s is not None else _env_float("LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)
        self.max_retries = max_retries
        self._client = client

    def create_message(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens_out,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(headers=headers, payload=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries:
                        continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Failed to call Anthropic Messages API")

    def _request(self, *, headers: dict[str, str], payload: dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload, timeout=self.timeout_s)

        with httpx.Client(timeout=self.timeout_s) as client:
            return client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
