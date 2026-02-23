import asyncio

from mitra_app.research import ResearchError, SearchItem, run_research


def test_run_research_without_search_key_falls_back_to_llm_only(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    items, summary = asyncio.run(run_research("ai agents"))

    assert items == []
    assert "No web search (search not configured)." in summary
    assert "LLM-only answer" in summary


def test_run_research_with_search_key_uses_search_and_summary(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "token")

    async def fake_search_top5(query: str):
        assert query == "ai agents"
        return [SearchItem(title="A", url="https://a.test", snippet="alpha")]

    async def fake_summarize(query: str, items: list[SearchItem]):
        assert query == "ai agents"
        assert len(items) == 1
        return "- summary"

    monkeypatch.setattr("mitra_app.research.search_top5", fake_search_top5)
    monkeypatch.setattr("mitra_app.research.summarize_with_sonnet", fake_summarize)

    items, summary = asyncio.run(run_research("ai agents"))

    assert items[0].title == "A"
    assert summary == "- summary"


def test_run_research_with_search_key_sanitizes_errors(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "token")

    async def fake_search_top5(query: str):
        raise RuntimeError("sensitive backend failure")

    monkeypatch.setattr("mitra_app.research.search_top5", fake_search_top5)

    try:
        asyncio.run(run_research("ai agents"))
    except ResearchError as exc:
        assert str(exc) == "Research failed. Please try again later."
    else:
        raise AssertionError("ResearchError was expected")
