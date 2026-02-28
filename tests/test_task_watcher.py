import asyncio
from pathlib import Path

from mitra_app import main
from mitra_app.task_tracker import TaskTrackerStore


class _LinkedPr:
    def __init__(self, number: int, html_url: str, title: str = ""):
        self.number = number
        self.html_url = html_url
        self.title = title


class _PrStatus:
    def __init__(self, number: int, html_url: str, state: str = "open", draft: bool = False, merged: bool = False):
        self.number = number
        self.html_url = html_url
        self.state = state
        self.draft = draft
        self.merged = merged


def test_task_watcher_sends_notification_only_once_for_same_state(monkeypatch, tmp_path: Path):
    tracker = TaskTrackerStore(tmp_path / "tracked_tasks.json")
    tracker.add(issue_number=101, chat_id=123)

    sent: list[tuple[int, str]] = []

    async def fake_send_message(chat_id: int, text: str):
        sent.append((chat_id, text))
        return True

    async def fake_find_linked_pr(issue_number: int):
        assert issue_number == 101
        return _LinkedPr(number=55, html_url="https://github.com/o/r/pull/55")

    async def fake_get_pr_status(pr_number: int):
        assert pr_number == 55
        return _PrStatus(number=55, html_url="https://github.com/o/r/pull/55", state="open")

    monkeypatch.setattr(main, "_task_tracker", tracker)
    monkeypatch.setattr(main, "send_message", fake_send_message)
    monkeypatch.setattr(main.github, "find_linked_pr", fake_find_linked_pr)
    monkeypatch.setattr(main.github, "get_pr_status", fake_get_pr_status)

    asyncio.run(main._run_task_watcher_iteration())
    asyncio.run(main._run_task_watcher_iteration())

    assert len(sent) == 1
    assert sent[0][0] == 123
    assert "issue #101" in sent[0][1]
    assert tracker.load()[0].last_notified_state == "pr_open"
