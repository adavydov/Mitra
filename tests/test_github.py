from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from mitra_app.github import (
    GitHubNotConfigured,
    create_issue,
    get_issue,
    find_linked_pr,
    get_pr_checks_summary,
    get_pr_status,
    list_prs,
)


class FakeResponse:
    def __init__(self, payload: Any):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class FakeAsyncClient:
    def __init__(self, *args: Any, **kwargs: Any):
        self._get_handler: Callable[[str, dict[str, Any], dict[str, str]], FakeResponse] | None = kwargs.pop(
            "_get_handler", None
        )
        self._post_handler: Callable[[str, dict[str, Any], dict[str, str]], FakeResponse] | None = kwargs.pop(
            "_post_handler", None
        )

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str],
    ) -> FakeResponse:
        assert self._get_handler is not None
        return self._get_handler(url, params or {}, headers)

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        assert self._post_handler is not None
        return self._post_handler(url, json, headers)


def test_create_issue_posts_to_github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    captured: dict[str, Any] = {}

    def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return FakeResponse(
            {
                "number": 42,
                "title": payload["title"],
                "body": payload["body"],
                "state": "open",
                "html_url": "https://github.com/owner/repo/issues/42",
                "labels": [{"name": "bug"}],
            }
        )

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _post_handler=fake_post, **kwargs),
    )

    issue = asyncio.run(create_issue("Title", "Body", ["bug"]))

    assert captured["url"] == "https://api.github.com/repos/owner/repo/issues"
    assert captured["payload"] == {"title": "Title", "body": "Body", "labels": ["bug"]}
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert issue.number == 42
    assert issue.labels == ["bug"]


def test_get_issue_reads_github_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        assert params == {}
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert url == "https://api.github.com/repos/owner/repo/issues/7"
        return FakeResponse(
            {
                "number": 7,
                "title": "Issue 7",
                "body": "Details",
                "state": "open",
                "html_url": "https://github.com/owner/repo/issues/7",
                "labels": [{"name": "enhancement"}],
            }
        )

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, **kwargs),
    )

    issue = asyncio.run(get_issue(7))

    assert issue.number == 7
    assert issue.title == "Issue 7"
    assert issue.labels == ["enhancement"]


def test_list_prs_and_get_pr_status(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if url.endswith("/pulls"):
            assert params == {"state": "open"}
            return FakeResponse(
                [
                    {
                        "number": 11,
                        "title": "PR 11",
                        "state": "open",
                        "draft": False,
                        "html_url": "https://github.com/owner/repo/pull/11",
                    }
                ]
            )

        assert url.endswith("/pulls/11")
        return FakeResponse(
            {
                "number": 11,
                "state": "open",
                "draft": False,
                "merged": False,
                "mergeable": True,
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/owner/repo/pull/11",
            }
        )

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, **kwargs),
    )

    prs = asyncio.run(list_prs())
    pr_status = asyncio.run(get_pr_status(11))

    assert len(prs) == 1
    assert prs[0].number == 11
    assert pr_status.number == 11
    assert pr_status.head_sha == "abc123"
    assert pr_status.mergeable is True


def test_github_requires_token_and_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)

    with pytest.raises(GitHubNotConfigured):
        asyncio.run(list_prs())


def test_find_linked_pr_in_pr_body(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if url.endswith("/pulls"):
            assert params["state"] == "all"
            return FakeResponse([
                {
                    "number": 55,
                    "title": "feat: support issue refs",
                    "body": "Fixes #42",
                    "html_url": "https://github.com/owner/repo/pull/55",
                }
            ])

        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, **kwargs),
    )

    pr = asyncio.run(find_linked_pr(42))

    assert pr is not None
    assert pr.number == 55
    assert pr.html_url.endswith("/pull/55")


def test_find_linked_pr_from_issue_comments(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if url.endswith("/pulls"):
            return FakeResponse([])
        if url.endswith("/issues/99/comments"):
            return FakeResponse([{"body": "tracked in https://github.com/owner/repo/pull/21"}])
        if url.endswith("/pulls/21"):
            return FakeResponse({"number": 21, "title": "PR 21", "html_url": "https://github.com/owner/repo/pull/21"})

        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, **kwargs),
    )

    pr = asyncio.run(find_linked_pr(99))

    assert pr is not None
    assert pr.number == 21


def test_get_pr_checks_summary(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    def fake_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if url.endswith("/check-runs"):
            return FakeResponse(
                {
                    "check_runs": [
                        {"status": "completed", "conclusion": "success"},
                        {"status": "completed", "conclusion": "failure"},
                        {"status": "in_progress", "conclusion": None},
                    ]
                }
            )
        if url.endswith("/status"):
            return FakeResponse(
                {
                    "statuses": [
                        {"state": "success"},
                        {"state": "pending"},
                    ]
                }
            )

        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "mitra_app.github.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(*args, _get_handler=fake_get, **kwargs),
    )

    summary = asyncio.run(get_pr_checks_summary("abc123"))

    assert summary.total == 5
    assert summary.successful == 2
    assert summary.failed == 1
    assert summary.pending == 2
