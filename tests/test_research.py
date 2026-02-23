import asyncio

import pytest

from mitra_app.research import ResearchError, SearchItem, run_research


def test_run_research_reports_missing_search_key(monkeypatch):
    async def fake_brave_web_search(query: str):
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured")

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)

    with pytest.raises(ResearchError, match=r"Search not configured \(missing BRAVE_SEARCH_API_KEY\)"):
        asyncio.run(run_research("ai agents"))


def test_run_research_reports_missing_llm_key(monkeypatch):
    async def fake_brave_web_search(query: str):
        from mitra_app.search import SearchResult

        return [SearchResult(title="A", url="https://a.test", description="alpha")]

    async def fake_summarize(query: str, items: list[SearchItem]):
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)
    monkeypatch.setattr("mitra_app.research.summarize_with_sonnet", fake_summarize)

    with pytest.raises(ResearchError, match="LLM not configured"):
        asyncio.run(run_research("ai agents"))


def test_run_research_reports_budget_or_rate_limit(monkeypatch):
    from mitra_app.search import SearchRateLimitExceeded

    async def fake_brave_web_search(query: str):
        raise SearchRateLimitExceeded("max 5 requests per minute")

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)

    with pytest.raises(ResearchError, match="Denied by budget/rate limit: max 5 requests per minute"):
        asyncio.run(run_research("ai agents"))


def test_run_research_reports_other_exception_with_short_reason(monkeypatch):
    async def fake_brave_web_search(query: str):
        raise RuntimeError("temporary upstream issue")

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)

    with pytest.raises(ResearchError, match="Research failed: temporary upstream issue"):
        asyncio.run(run_research("ai agents"))
