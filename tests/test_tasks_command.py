from pathlib import Path

from fastapi.testclient import TestClient

from mitra_app.main import app
from mitra_app.task_tracker import TaskTrackerStore


def test_tasks_command_lists_tracked_tasks(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    tracker = TaskTrackerStore(tmp_path / "tracked_tasks.json")
    tracker.add(issue_number=77, chat_id=123)
    tracker.update_last_notified_state(issue_number=77, state="pr_open")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main._task_tracker", tracker)
    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"message": {"text": "/tasks", "chat": {"id": 123}, "from": {"id": 123}}},
        )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == 123
    assert "Активные задачи:" in calls[0][1]
    assert "issue #77" in calls[0][1]
    assert "pr_open" in calls[0][1]


def test_task_command_adds_issue_to_tracker(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    tracker = TaskTrackerStore(tmp_path / "tracked_tasks.json")

    async def fake_send_message(chat_id: int, text: str):
        return True

    def fake_build_task_spec(request_text: str):
        return {
            "title": "Добавить /hello",
            "summary": "Описание",
            "components": [],
            "required_env_secrets": [],
            "new_commands": ["/hello"],
            "acceptance_criteria": ["ok"],
            "tests_to_add": [],
            "risk_level": "R1",
            "allowed_file_scope": ["mitra_app/*", "tests/*"],
        }

    async def fake_create_github_issue(title: str, body: str):
        return 501, "https://github.com/o/r/issues/501"

    monkeypatch.setattr("mitra_app.main._task_tracker", tracker)
    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)

    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={
                "message": {
                    "text": "/task Добавь /hello в GitHub, секреты в env, risk R1, acceptance criteria ok, дедлайн 2026-01-01",
                    "chat": {"id": 123},
                    "from": {"id": 123},
                }
            },
        )

    assert response.status_code == 200
    tracked = tracker.load()
    assert len(tracked) == 1
    assert tracked[0].issue_number == 501
    assert tracked[0].chat_id == 123
