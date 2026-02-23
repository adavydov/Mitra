import asyncio

import pytest

from mitra_app.research import run_research
from mitra_app.search import SearchResult


@pytest.mark.parametrize("api_key", ["", "   "])
def test_run_research_without_brave_key_falls_back_to_llm_only(monkeypatch, api_key):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", api_key)

    called = {"search": False, "summarize": False}

    async def fake_brave_web_search(query: str):
        called["search"] = True
        return [SearchResult(title="X", url="https://x.test", description="desc")]

    async def fake_summarize_with_sonnet(query: str, items):
        called["summarize"] = True
        assert query == "ai agents"
        assert items == []
        return "- LLM-only answer"

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)
    monkeypatch.setattr("mitra_app.research.summarize_with_sonnet", fake_summarize_with_sonnet)

    items, summary = asyncio.run(run_research("ai agents"))

    assert called["search"] is False
    assert called["summarize"] is True
    assert items == []
    assert summary.startswith("No web search (search not configured).")


def test_run_research_with_brave_key_uses_search(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "configured-key")

    called = {"search": False, "summarize": False}

    async def fake_brave_web_search(query: str):
        called["search"] = True
        assert query == "ai agents"
        return [
            SearchResult(title="A", url="https://a.test", description="alpha"),
            SearchResult(title="B", url="https://b.test", description="beta"),
        ]

    async def fake_summarize_with_sonnet(query: str, items):
        called["summarize"] = True
        assert query == "ai agents"
        assert [item.title for item in items] == ["A", "B"]
        return "- Searched summary"

    monkeypatch.setattr("mitra_app.research.brave_web_search", fake_brave_web_search)
    monkeypatch.setattr("mitra_app.research.summarize_with_sonnet", fake_summarize_with_sonnet)

    items, summary = asyncio.run(run_research("ai agents"))

    assert called["search"] is True
    assert called["summarize"] is True
    assert [item.url for item in items] == ["https://a.test", "https://b.test"]
    assert summary == "- Searched summary"
