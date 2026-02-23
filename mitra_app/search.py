from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

import httpx


class SearchRateLimitExceeded(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    description: str


class SearchRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def check_and_consume(self) -> bool:
        now = monotonic()
        boundary = now - self._window_seconds

        with self._lock:
            while self._timestamps and self._timestamps[0] <= boundary:
                self._timestamps.popleft()

            if len(self._timestamps) >= self._max_requests:
                return False

            self._timestamps.append(now)
            return True


_rate_limiter = SearchRateLimiter(max_requests=5, window_seconds=60)


async def brave_web_search(query: str) -> list[SearchResult]:
    api_token = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_token:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured")

    if not _rate_limiter.check_and_consume():
        raise SearchRateLimitExceeded("Search rate limit exceeded: max 5 requests per minute")

    params = {"q": query}
    headers = {"X-Subscription-Token": api_token}

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get("https://api.search.brave.com/res/v1/web/search", params=params, headers=headers)
        response.raise_for_status()
        payload: dict = response.json()

    web_payload = payload.get("web") if isinstance(payload, dict) else None
    raw_results = web_payload.get("results") if isinstance(web_payload, dict) else []

    output: list[SearchResult] = []
    for raw in raw_results[:5]:
        if not isinstance(raw, dict):
            continue
        output.append(
            SearchResult(
                title=str(raw.get("title", "")),
                url=str(raw.get("url", "")),
                description=str(raw.get("description", "")),
            )
        )

    return output


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "No results found"

    lines = ["Top 5 results:"]
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result.title}")
        lines.append(f"{result.url}")
        lines.append(result.description)
        lines.append("")

    return "\n".join(lines).strip()
