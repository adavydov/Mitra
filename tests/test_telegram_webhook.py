import json

from fastapi.testclient import TestClient

from mitra_app.drive import DriveNotConfiguredError, DriveUploadResult
from mitra_app.main import RecentUpdateDeduplicator, _load_allowed_user_ids, app


client = TestClient(app)


def test_webhook_without_secret_header_returns_401(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    response = client.post(
        "/telegram/webhook",
        json={"message": {"text": "/status", "chat": {"id": 123}}},
    )

    assert response.status_code == 401


def test_webhook_with_secret_status_returns_200_and_sends_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/status", "chat": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [(123, "Mitra alive")]


def test_load_allowed_user_ids_parses_and_ignores_invalid_values(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", " 1,2, bad, ,3 ")

    assert _load_allowed_user_ids() == {1, 2, 3}


def test_allowlist_not_configured_blocks_non_status_commands(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.delenv("ALLOWED_TELEGRAM_USER_IDS", raising=False)

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report blocked", "chat": {"id": 123}, "from": {"id": 999}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Allowlist not configured. Set ALLOWED_TELEGRAM_USER_IDS.")]


def test_allowlist_not_configured_allows_whoami(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.delenv("ALLOWED_TELEGRAM_USER_IDS", raising=False)

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/whoami", "chat": {"id": 123}, "from": {"id": 999}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "user_id=999, chat_id=123")]


def test_allowlist_denied_user_returns_200_without_sending_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "101")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/status", "chat": {"id": 123}, "from": {"id": 999}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == []


def test_recent_update_deduplicator_evicts_oldest_entries():
    deduplicator = RecentUpdateDeduplicator(max_size=2)

    assert deduplicator.is_duplicate(100) is False
    assert deduplicator.is_duplicate(101) is False
    assert deduplicator.is_duplicate(100) is True

    assert deduplicator.is_duplicate(102) is False
    assert deduplicator.is_duplicate(101) is False


def test_duplicate_update_id_returns_200_without_sending_message_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_audit_dedup(update_id: int, user_id: int | None, chat_id: int | None):
        audits.append((update_id, user_id, chat_id))

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._audit_dedup", fake_audit_dedup)
    monkeypatch.setattr("mitra_app.main._recent_update_deduplicator", RecentUpdateDeduplicator(max_size=10))

    payload = {
        "update_id": 555,
        "message": {"text": "/status", "chat": {"id": 123}, "from": {"id": 987}},
    }

    first_response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json=payload,
    )
    second_response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert calls == [(123, "Mitra alive")]
    assert audits == [(555, 987, 123)]


def test_report_upload_success_replies_with_link_and_audits(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    captured = {}

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        captured["title"] = title
        captured["body"] = markdown_body
        return DriveUploadResult(file_id="file-123", web_view_link="https://drive.test/view")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report Quarterly risk update", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Report uploaded: https://drive.test/view")]
    assert captured["title"].startswith("report-")
    assert "quarterly-risk-update" in captured["title"]
    assert "Quarterly risk update" in captured["body"]
    assert "timestamp:" in captured["body"]
    assert "action_id:" in captured["body"]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(events[-1])
    assert payload["file_id"] == "file-123"
    assert payload["outcome"] == "success"
    assert payload["action_id"].startswith("act-")
    assert payload["link"] == "https://drive.test/view"


def test_report_drive_disabled_replies_and_audits(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise DriveNotConfiguredError("disabled")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Drive disabled")]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(events[-1])
    assert payload["file_id"] == ""
    assert payload["outcome"] == "drive_disabled"


def test_report_upload_without_web_view_link_uses_file_id(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        return DriveUploadResult(file_id="file-xyz", web_view_link=None)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Report uploaded: file-xyz")]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(events[-1])
    assert payload["file_id"] == "file-xyz"
    assert payload["link"] == "file-xyz"
    assert payload["outcome"] == "success"


def test_webhook_returns_200_when_send_message_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    async def fake_send_message(chat_id: int, text: str):
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/status", "chat": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
