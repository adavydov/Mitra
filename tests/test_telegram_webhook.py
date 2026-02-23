import json
import logging
import os

import httplib2
from googleapiclient.errors import HttpError

from fastapi.testclient import TestClient

from mitra_app.drive import DriveNotConfiguredError, DriveUploadResult, OAuthRefreshInvalidGrant
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


def test_think_command_returns_short_read_only_response(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def forbidden_upload_markdown(*args, **kwargs):
        raise AssertionError("/think must not touch Drive")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", forbidden_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/think Составь план запуска", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(calls) == 1
    reply = calls[0][1]
    assert "Что сделал:" in reply
    assert "Допущения:" in reply
    assert "Риск:" in reply


def test_think_command_redacts_secret_assignments_and_limits_prompt(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    long_tail = "x" * 1200
    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": f"/think Проверь TELEGRAM_BOT_TOKEN=12345 и хвост {long_tail}",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    reply = calls[0][1]
    assert "12345" not in reply
    assert "[REDACTED]" in reply
    assert len(reply) < 450


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

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)
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
    payload = [entry for entry in audits if entry.get("event") == "telegram_dedup"][0]
    assert payload["event"] == "telegram_dedup"
    assert payload["action_id"].startswith("act-")
    assert payload["telegram_update_id"] == 555
    assert payload["user_id"] == 987
    assert payload["chat_id"] == 123
    assert payload["action_type"] == "dedup_check"
    assert payload["outcome"] == "dedup"
    assert payload["log_level"] == "info"


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
    assert calls == [(123, "Saved: https://drive.test/view")]
    assert captured["title"].startswith("mitra-report ")
    assert "Quarterly risk update" in captured["body"]
    assert "timestamp:" in captured["body"]
    assert "user_id: 123" in captured["body"]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = [json.loads(line) for line in events if "file_id" in json.loads(line)][-1]
    assert payload["file_id"] == "file-123"
    assert payload["outcome"] == "success"
    assert payload["action_id"].startswith("act-")
    assert payload["telegram_update_id"] is None
    assert payload["user_id"] == 123
    assert payload["action_type"] == "/report"
    assert payload["log_level"] == "info"
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
    payload = [json.loads(line) for line in events if "file_id" in json.loads(line)][-1]
    assert payload["file_id"] == ""
    assert payload["user_id"] == 123
    assert payload["action_type"] == "/report"
    assert payload["log_level"] == "error"
    assert payload["outcome"] == "drive_disabled"


def test_report_http_error_replies_with_sanitized_status_and_reason(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        response = httplib2.Response({"status": "403", "reason": "Forbidden"})
        content = b'{"error": {"errors": [{"reason": "insufficientFilePermissions"}]}}'
        raise HttpError(resp=response, content=content)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
        )

    assert response.status_code == 200
    assert calls == [(123, "Drive error: 403 insufficientFilePermissions")]
    assert any(record.message == "report_upload_failed" and record.exc_info for record in caplog.records)


def test_report_generic_error_does_not_leak_exception_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise RuntimeError("api_key=secret-token")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Report failed")]


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
    assert calls == [(123, "Saved: file-xyz")]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = [json.loads(line) for line in events if "file_id" in json.loads(line)][-1]
    assert payload["file_id"] == "file-xyz"
    assert payload["link"] == "file-xyz"
    assert payload["outcome"] == "success"




def test_report_without_text_returns_usage_and_does_not_crash(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [(123, "Usage: /report <text>")]



def test_report_http_error_replies_with_sanitized_reason_and_logs_traceback(monkeypatch, caplog):
    from googleapiclient.errors import HttpError

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    class FakeResp:
        status = 403
        reason = "Forbidden"

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise HttpError(FakeResp(), b'{"error":{"errors":[{"reason":"insufficientFilePermissions"}]}}', uri="https://drive.test")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    with caplog.at_level("ERROR"):
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
        )

    assert response.status_code == 200
    assert calls == [(123, "Drive error: 403 insufficientFilePermissions")]
    assert any(record.message == "report_upload_failed" and record.exc_info for record in caplog.records)


def test_report_drive_disabled_logs_traceback(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise DriveNotConfiguredError("disabled")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    with caplog.at_level("ERROR"):
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
        )

    assert response.status_code == 200
    assert calls == [(123, "Drive disabled")]
    assert any(record.message == "report_upload_drive_not_configured" and record.exc_info for record in caplog.records)

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




def test_webhook_returns_status_ok_when_audit_fails(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_log_event(event: dict[str, object]):
        raise OSError("audit down")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/status", "chat": {"id": 123}, "from": {"id": 111}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [(123, "Mitra alive")]

def test_drive_check_reports_service_account_mode(monkeypatch):
    monkeypatch.delenv("DRIVE_OAUTH_REFRESH_TOKEN", raising=False)


def test_drive_check_command_success_replies_with_auth_mode_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh-token")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        assert title == "mitra-drive-check"
        assert markdown_body == "test"
        return DriveUploadResult(file_id="file-123", web_view_link="https://drive.test/view")

    async def fake_delete_file(file_id: str):
        assert file_id == "file-123"
        return None

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.main.delete_file", fake_delete_file)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/drive_check", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Drive OK (auth=oauth)")]
    drive_check_audit = next(event for event in audits if event.get("event") == "drive_check")
    assert drive_check_audit == {
        "event": "drive_check",
        "user_id": 123,
        "chat_id": 123,
        "auth_mode": "oauth",
        "outcome": "success",
        "detail": "upload+delete ok",
    }


def test_drive_check_command_http_error_returns_sanitized_reason_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    class FakeResp:
        status = 403
        reason = "Forbidden"

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise HttpError(FakeResp(), b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}', uri="https://drive.test")

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/drive_check", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Drive error: 403 insufficientPermissions")]
    drive_check_audit = next(event for event in audits if event.get("event") == "drive_check")
    assert drive_check_audit == {
        "event": "drive_check",
        "user_id": 123,
        "chat_id": 123,
        "auth_mode": "service_account",
        "outcome": "error",
        "detail": "Drive error: 403 insufficientPermissions",
    }


def test_drive_check_endpoint_returns_ok_with_auth_mode(monkeypatch):
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh-token")

    response = client.get("/drive_check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "oauth"


def test_drive_check_endpoint_returns_specific_http_error(monkeypatch):
    monkeypatch.delenv("DRIVE_OAUTH_REFRESH_TOKEN", raising=False)

    response = client.get("/drive_check")

    assert response.status_code == 200
    assert response.json() == {"auth_mode": "service_account"}
def test_startup_logs_drive_auth_mode(monkeypatch):
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh-token")

    captured: dict[str, object] = {}

    async def fake_ensure_webhook():
        return True, "ok"

    def fake_info(message, extra=None):
        captured["message"] = message
        captured["extra"] = extra

    monkeypatch.setattr("mitra_app.main.ensure_webhook", fake_ensure_webhook)
    monkeypatch.setattr("mitra_app.main.logger.info", fake_info)

    import asyncio
    from mitra_app.main import startup_sync_webhook

    asyncio.run(startup_sync_webhook())

    assert captured["message"] == "drive_auth_state"
    assert captured["extra"]["mode"] == "oauth"
    assert "last_refresh_at" in captured["extra"]


def test_oauth_status_command_returns_mode_and_last_refresh(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.get_drive_auth_mode", lambda: "oauth")
    monkeypatch.setattr("mitra_app.main.get_last_oauth_refresh_time", lambda: "2026-01-01T00:00:00+00:00")

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/oauth_status", "chat": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "auth_mode=oauth, last_refresh_at=2026-01-01T00:00:00+00:00")]


def test_pr_status_command_uses_builder_and_returns_result(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_build_pr_status_reply(ref: str) -> str:
        assert ref == "42"
        return "PR: #42 (есть)\nchecks: success=3, failed=0, pending=0\nauto-merge: нет\nссылка: https://github.com/o/r/pull/42"

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_pr_status_reply", fake_build_pr_status_reply)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/pr_status 42", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [
        (123, "PR: #42 (есть)\nchecks: success=3, failed=0, pending=0\nauto-merge: нет\nссылка: https://github.com/o/r/pull/42")
    ]


def test_pr_status_command_without_argument_returns_usage(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/pr_status", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Usage: /pr_status <issue#|pr#>")]


def test_report_oauth_expired_replies_with_reauthorize_message(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise OAuthRefreshInvalidGrant("OAuth expired. Re-authorize required.")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report Something", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "OAuth expired. Re-authorize required.")]

    events = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(events[-1])
    assert payload["outcome"] == "oauth_expired"


def test_research_without_query_returns_usage(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/research", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Usage: /research <query>")]


def test_research_returns_search_results_and_summary(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_run_research(query: str):
        from mitra_app.research import SearchItem

        return [
            SearchItem(title="A", url="https://a.test", snippet="alpha"),
            SearchItem(title="B", url="https://b.test", snippet="beta"),
        ], "- Итог 1\n- Итог 2"

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.run_research", fake_run_research)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/research ai agents", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == 123
    assert "Top 5 results" in calls[0][1]
    assert "Что нашёл:" in calls[0][1]
    assert "/report <text>" in calls[0][1]
