from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
import re

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


@dataclass
class GitHubChecksSummary:
    total: int
    successful: int
    failed: int
    pending: int


@dataclass
class GitHubLinkedPullRequest:
    number: int
    html_url: str
    title: str


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


def _mentions_issue(text: str | None, issue_number: int) -> bool:
    if not text:
        return False

    patterns = [
        rf"#{issue_number}\b",
        rf"GH-{issue_number}\b",
        rf"issues/{issue_number}\b",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _extract_pr_number(value: str) -> int | None:
    match = re.search(r"/pull/(\d+)\b", value)
    if match:
        return int(match.group(1))

    hash_match = re.search(r"#(\d+)\b", value)
    if hash_match:
        return int(hash_match.group(1))

    return None


async def find_linked_pr(issue_number: int) -> GitHubLinkedPullRequest | None:
    token, repo = _read_config()

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": "all", "per_page": 100},
            headers=_headers(token),
        )
        response.raise_for_status()
        pulls_payload = response.json()

        for raw_pr in pulls_payload:
            if not isinstance(raw_pr, dict):
                continue
            title = str(raw_pr.get("title", ""))
            body = str(raw_pr.get("body") or "")
            if _mentions_issue(title, issue_number) or _mentions_issue(body, issue_number):
                return GitHubLinkedPullRequest(
                    number=int(raw_pr.get("number", 0)),
                    html_url=str(raw_pr.get("html_url", "")),
                    title=title,
                )

        comments_response = await client.get(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100},
            headers=_headers(token),
        )
        comments_response.raise_for_status()
        comments_payload = comments_response.json()

        for comment in comments_payload:
            if not isinstance(comment, dict):
                continue
            body = str(comment.get("body") or "")
            pr_number = _extract_pr_number(body)
            if not pr_number:
                continue

            pr_response = await client.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                headers=_headers(token),
            )
            pr_response.raise_for_status()
            pr_payload: dict[str, Any] = pr_response.json()
            return GitHubLinkedPullRequest(
                number=int(pr_payload.get("number", pr_number)),
                html_url=str(pr_payload.get("html_url", "")),
                title=str(pr_payload.get("title", "")),
            )

    return None


async def get_pr_checks_summary(head_sha: str) -> GitHubChecksSummary:
    token, repo = _read_config()

    async with httpx.AsyncClient(timeout=10) as client:
        checks_response = await client.get(
            f"https://api.github.com/repos/{repo}/commits/{head_sha}/check-runs",
            headers={**_headers(token), "Accept": "application/vnd.github+json"},
        )
        checks_response.raise_for_status()
        checks_payload: dict[str, Any] = checks_response.json()

        status_response = await client.get(
            f"https://api.github.com/repos/{repo}/commits/{head_sha}/status",
            headers=_headers(token),
        )
        status_response.raise_for_status()
        status_payload: dict[str, Any] = status_response.json()

    successful = 0
    failed = 0
    pending = 0

    for run in checks_payload.get("check_runs", []):
        if not isinstance(run, dict):
            continue
        status = str(run.get("status", ""))
        conclusion = str(run.get("conclusion", ""))
        if status != "completed":
            pending += 1
        elif conclusion == "success":
            successful += 1
        else:
            failed += 1

    for status_item in status_payload.get("statuses", []):
        if not isinstance(status_item, dict):
            continue
        state = str(status_item.get("state", ""))
        if state == "success":
            successful += 1
        elif state in {"pending", "queued"}:
            pending += 1
        else:
            failed += 1

    total = successful + failed + pending
    return GitHubChecksSummary(total=total, successful=successful, failed=failed, pending=pending)
