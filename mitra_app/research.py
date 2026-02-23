from __future__ import annotations

import os
import logging
from dataclasses import dataclass

import httpx

from mitra_app.search import brave_web_search


logger = logging.getLogger(__name__)

_NO_SEARCH_DISCLAIMER = "No web search (search not configured)."


class ResearchError(RuntimeError):
    """Raised when research pipeline cannot complete."""


@dataclass
class SearchItem:
    title: str
    url: str
    snippet: str


async def search_top5(query: str) -> list[SearchItem]:
    results = await brave_web_search(query)
    return [SearchItem(title=item.title, url=item.url, snippet=item.description) for item in results[:5]]




async def summarize_with_sonnet(query: str, items: list[SearchItem]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_summary(query, items)

    model = os.getenv("RESEARCH_SONNET_MODEL", "claude-3-5-sonnet-latest")
    max_tokens = int(os.getenv("RESEARCH_SONNET_MAX_TOKENS", "300"))
    prompt = _build_sonnet_prompt(query, items)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            response.raise_for_status()
        payload = response.json()
        content = payload.get("content") or []
        text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
        summary = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
        return summary or _fallback_summary(query, items)
    except Exception:
        return _fallback_summary(query, items)


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

    search_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not search_api_key:
        summary = await summarize_without_search(cleaned)
        return [], f"{_NO_SEARCH_DISCLAIMER}\n{summary}"

    try:
        items = await search_top5(cleaned)
        summary = await summarize_with_sonnet(cleaned, items)
        return items, summary
    except Exception as exc:
        logger.exception("research_pipeline_failed")
        raise ResearchError("Research failed. Please try again later.") from exc


async def summarize_without_search(query: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "LLM-only answer without fresh web sources. "
            f"Working hypothesis for '{query}': уточните контекст, критерии и ограничения, "
            "чтобы получить более точный вывод."
        )

    prompt = "\n".join(
        [
            f"Запрос: {query}",
            "Сформируй короткий ответ на русском без использования веб-поиска.",
            "Явно укажи, что ответ основан на общих знаниях модели и может быть устаревшим.",
            "Формат: 3-6 буллетов + строка с ограничениями.",
        ]
    )

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": os.getenv("RESEARCH_SONNET_MODEL", "claude-3-5-sonnet-latest"),
        "max_tokens": int(os.getenv("RESEARCH_SONNET_MAX_TOKENS", "300")),
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            response.raise_for_status()
        payload = response.json()
        content = payload.get("content") or []
        text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
        summary = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
        return summary or f"Базовый ответ без веб-поиска по запросу '{query}'."
    except Exception:
        logger.exception("research_llm_only_failed")
        return (
            "LLM-only answer without fresh web sources. "
            f"For '{query}' provide domain, geography, and timeframe to improve quality."
        )


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
