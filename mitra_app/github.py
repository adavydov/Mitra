from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class GitHubNotConfigured(RuntimeError):
    """Raised when GitHub integration is missing required configuration."""


@dataclass
class GitHubIssue:
    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    labels: list[str]


@dataclass
class GitHubPullRequest:
    number: int
    title: str
    state: str
    draft: bool
    html_url: str


@dataclass
class GitHubPullRequestStatus:
    number: int
    state: str
    draft: bool
    merged: bool | None
    mergeable: bool | None
    head_sha: str
    html_url: str


def _read_config() -> tuple[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    if not token or not repo:
        raise GitHubNotConfigured("Missing GITHUB_TOKEN or GITHUB_REPO")
    return token, repo


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _to_issue(payload: dict[str, Any]) -> GitHubIssue:
    labels = payload.get("labels") or []
    return GitHubIssue(
        number=int(payload.get("number", 0)),
        title=str(payload.get("title", "")),
        body=payload.get("body"),
        state=str(payload.get("state", "")),
        html_url=str(payload.get("html_url", "")),
        labels=[str(label.get("name", "")) for label in labels if isinstance(label, dict)],
    )


def _to_pr(payload: dict[str, Any]) -> GitHubPullRequest:
    return GitHubPullRequest(
        number=int(payload.get("number", 0)),
        title=str(payload.get("title", "")),
        state=str(payload.get("state", "")),
        draft=bool(payload.get("draft", False)),
        html_url=str(payload.get("html_url", "")),
    )


async def create_issue(title: str, body: str, labels: list[str] | None = None) -> GitHubIssue:
    token, repo = _read_config()
    payload = {
        "title": title,
        "body": body,
        "labels": labels or [],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"https://api.github.com/repos/{repo}/issues",
            json=payload,
            headers=_headers(token),
        )
        response.raise_for_status()

    return _to_issue(response.json())


async def get_issue(number: int) -> GitHubIssue:
    token, repo = _read_config()

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/issues/{number}",
            headers=_headers(token),
        )
        response.raise_for_status()

    return _to_issue(response.json())


async def list_prs(state: str = "open") -> list[GitHubPullRequest]:
    token, repo = _read_config()

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": state},
            headers=_headers(token),
        )
        response.raise_for_status()

    payload = response.json()
    return [_to_pr(item) for item in payload if isinstance(item, dict)]


async def get_pr_status(number: int) -> GitHubPullRequestStatus:
    token, repo = _read_config()

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{number}",
            headers=_headers(token),
        )
        response.raise_for_status()

    payload = response.json()
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    return GitHubPullRequestStatus(
        number=int(payload.get("number", number)),
        state=str(payload.get("state", "")),
        draft=bool(payload.get("draft", False)),
        merged=payload.get("merged"),
        mergeable=payload.get("mergeable"),
        head_sha=str(head.get("sha", "")),
        html_url=str(payload.get("html_url", "")),
    )
