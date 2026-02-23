from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from mitra_app.search import brave_web_search


class ResearchError(RuntimeError):
    """Raised when research pipeline cannot complete."""


@dataclass
class SearchItem:
    title: str
    url: str
    snippet: str


async def search_top5(query: str) -> list[SearchItem]:
    params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get("https://api.duckduckgo.com/", params=params)
        response.raise_for_status()
    payload = response.json()

    candidates: list[SearchItem] = []
    for topic in payload.get("RelatedTopics", []):
        candidates.extend(_extract_topics(topic))
        if len(candidates) >= 5:
            break

    if not candidates and payload.get("AbstractText"):
        candidates.append(
            SearchItem(
                title=str(payload.get("Heading") or query),
                url=str(payload.get("AbstractURL") or ""),
                snippet=str(payload.get("AbstractText") or ""),
            )
        )

    return candidates[:5]


def _extract_topics(topic: dict[str, Any]) -> list[SearchItem]:
    if "Topics" in topic:
        nested: list[SearchItem] = []
        for item in topic.get("Topics", []):
            nested.extend(_extract_topics(item))
        return nested

    text = str(topic.get("Text") or "").strip()
    url = str(topic.get("FirstURL") or "").strip()
    if not text:
        return []

    title = text.split(" - ", 1)[0].strip()
    snippet = text.split(" - ", 1)[1].strip() if " - " in text else text
    return [SearchItem(title=title or "(untitled)", url=url, snippet=snippet)]


async def summarize_with_sonnet(query: str, items: list[SearchItem]) -> str:
    model = os.getenv("RESEARCH_SONNET_MODEL", "claude-sonnet-4-6")
    max_tokens = int(os.getenv("RESEARCH_SONNET_MAX_TOKENS", "300"))
    prompt = _build_sonnet_prompt(query, items)

    client = AnthropicClient(model=model, max_tokens_out=max_tokens)
    payload = client.create_message(messages=[{"role": "user", "content": prompt}])
    content = payload.get("content") or []
    text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
    summary = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
    return summary or _fallback_summary(query, items)


def _build_sonnet_prompt(query: str, items: list[SearchItem]) -> str:
    lines = [f"Запрос: {query}", "", "Топ-5 результатов поиска (заголовок, ссылка, сниппет):"]
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item.title}")
        lines.append(f"   URL: {item.url or 'n/a'}")
        lines.append(f"   Snippet: {item.snippet}")

    lines.extend(
        [
            "",
            "Сделай короткое резюме на русском: 'что нашёл'.",
            "Не придумывай факты, опирайся только на сниппеты выше.",
            "Формат: 3-6 буллетов и строка 'Ограничения поиска: ...'.",
        ]
    )
    return "\n".join(lines)


def _fallback_summary(query: str, items: list[SearchItem]) -> str:
    if not items:
        return f"По запросу '{query}' релевантных результатов не найдено."

    bullets = [f"- {item.title}: {item.snippet}" for item in items[:5]]
    return "\n".join(
        [
            "Кратко, что нашёл:",
            *bullets,
            "Ограничения поиска: использованы только поисковые сниппеты, без загрузки веб-страниц.",
        ]
    )


async def run_research(query: str) -> tuple[list[SearchItem], str]:
    cleaned = query.strip()
    if not cleaned:
        raise ResearchError("Usage: /research <query>")

    if os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
        results = await brave_web_search(cleaned)
        items = [
            SearchItem(title=result.title, url=result.url, snippet=result.description)
            for result in results
        ]
    else:
        items = []

    summary = await summarize_with_sonnet(cleaned, items)

    if not os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
        summary = "\n".join(["No web search (search not configured).", summary])

    return items, summary


def _is_budget_or_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "budget" in text or "rate limit" in text or "rate-limit" in text or "429" in text


def _short_reason(exc: Exception) -> str:
    reason = str(exc).strip() or exc.__class__.__name__
    sanitized = " ".join(reason.splitlines())
    return sanitized[:160]


def build_research_reply(query: str, items: list[SearchItem], summary: str) -> str:
    lines = [f"Research: {query}", "", "Top 5 results:"]
    if not items:
        lines.append("- Ничего релевантного не найдено")
    else:
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.title}")
            lines.append(f"   {item.url or 'n/a'}")

    lines.extend(["", "Что нашёл:", summary.strip(), "", "Подсказка: можно отправить это в Drive через /report <text>."])
    return "\n".join(lines)
