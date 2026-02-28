import asyncio
import json
import logging
import os
from dataclasses import dataclass

import httpx
import pytest

import httplib2
from googleapiclient.errors import HttpError

from fastapi.testclient import TestClient

from mitra_app.drive import DriveNotConfiguredError, DriveUploadResult, OAuthRefreshInvalidGrant
from mitra_app.main import (
    HELP_TEXT,
    RecentUpdateDeduplicator,
    _COMMAND_POLICIES,
    _REFLECT_SYSTEM_PROMPT,
    _extract_json_object,
    _build_task_spec,
    detect_capability_gaps,
    _build_pr_status_reply,
    _render_task_issue,
    _extract_think_prompt,
    _load_allowed_user_ids,
    _parse_evo_issue_command,
    _parse_pr_or_issue_ref,
    _pr_rate_limiter,
    _task_dialog_state_by_chat,
    app,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_task_rate_limiter_and_dialog_state():
    _pr_rate_limiter._events_by_user.clear()
    _task_dialog_state_by_chat.clear()


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



def test_webhook_blocks_probable_secret_and_sends_safe_guidance(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fail_create_issue(*args, **kwargs):
        raise AssertionError("task flow must be blocked on probable secret")

    audits = []

    def fake_log_event(event: dict[str, object]):
        audits.append(event)
        return "{}"

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fail_create_issue)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/task client secret=supersecretvalue123",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(calls) == 1
    assert "approved secret store" in calls[0][1]

    event = [entry for entry in audits if entry.get("event") == "telegram_secret_detected"][0]
    assert event["outcome"] == "blocked"
    assert "text" not in event
    assert "supersecretvalue123" not in json.dumps(event)



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


def test_search_without_brave_api_key_returns_not_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def forbidden_search(query: str):
        raise AssertionError("Search provider should not be called without API key")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.brave_web_search", forbidden_search)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/search ai news", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Search not configured")]


def test_start_command_lists_search(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "999")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/start", "chat": {"id": 123}, "from": {"id": 999}}},
    )

    assert response.status_code == 200
    assert calls == [
        (
            123,
            "Commands: /status, /oauth_status, /search <query>, /research <query>, /think <prompt>, "
            "/report <text>, /pr <title>\\n<spec>, /task <request>, /pr_status <issue#|pr#>, /drive_check, /budget, /smoke, /smoke_deep",
        )
    ]




def test_reflect_command_returns_summary_and_drive_link_without_thinking(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")

    sent_payloads = []

    class FakeTelegramResponse:
        def raise_for_status(self):
            return None

    class FakeTelegramClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            sent_payloads.append(json)
            return FakeTelegramResponse()

    async def fake_upload_markdown(title: str, markdown_body: str):
        assert "EVO-0 report" in markdown_body
        return DriveUploadResult(file_id="file-1", web_view_link="https://drive.test/evo0")

    class FakeReflectLlm:
        def __init__(self, *args, **kwargs):
            pass

        def create_message(self, *, messages, system):
            assert "AL0" in system
            assert "Текущая цель" in messages[0]["content"]
            return {
                "usage": {"input_tokens": 12, "output_tokens": 34},
                "content": [
                    {
                        "type": "text",
                        "text": "<thinking>hidden</thinking>\n- Гипотеза 1: улучшить intake\n- Гипотеза 2: ускорить smoke\n- Гипотеза 3: сократить шум аудита",
                    }
                ],
            }

    async def fake_render_budget():
        return "Budget day: 2026-01-01"

    llm_usage_calls = []
    drive_write_calls = []

    async def fake_record_llm_usage(payload):
        llm_usage_calls.append(payload)

    async def fake_record_drive_write(count: int = 1):
        drive_write_calls.append(count)

    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeReflectLlm)
    monkeypatch.setattr("mitra_app.main._load_current_goal", lambda: "Снизить MTTR")
    monkeypatch.setattr("mitra_app.main._load_recent_audit_events", lambda limit=12: [{"event": "e1"}])
    monkeypatch.setattr("mitra_app.main._deploy_revision_hint", lambda: "abc123")
    monkeypatch.setattr("mitra_app.main.budget_ledger.render_budget", fake_render_budget)
    monkeypatch.setattr("mitra_app.main.budget_ledger.record_llm_usage", fake_record_llm_usage)
    monkeypatch.setattr("mitra_app.main.budget_ledger.record_drive_write", fake_record_drive_write)
    monkeypatch.setattr("mitra_app.telegram.httpx.AsyncClient", lambda *args, **kwargs: FakeTelegramClient())

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/reflect", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert llm_usage_calls == [{"input_tokens": 12, "output_tokens": 34}]
    assert drive_write_calls == [1]
    assert len(sent_payloads) == 1
    reply = sent_payloads[0]["text"]
    assert "<thinking>" not in reply
    assert reply.count("- ") >= 3
    assert "https://drive.test/evo0" in reply

def test_extract_think_prompt_parses_relevant_command_only():
    assert _extract_think_prompt("/think Составь план") == "Составь план"
    assert _extract_think_prompt("/think\nСоставь план") == "Составь план"


def test_extract_think_prompt_ignores_irrelevant_prefixes():
    assert _extract_think_prompt("/thinker Составь план") == ""
    assert _extract_think_prompt("/thinking Составь план") == ""
    assert _extract_think_prompt("/think123 Составь план") == ""


def test_reflect_system_prompt_matches_expected_text():
    assert _REFLECT_SYSTEM_PROMPT == (
        "Ты формируешь только EVO-0 отчёт для человека-оператора в режиме AL0. "
        "Не выполняй действия, не вызывай инструменты и не предлагай автозапуски. "
        "Верни только итоговый отчёт без chain-of-thought."
    )

def test_think_command_returns_short_read_only_response(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def forbidden_upload_markdown(*args, **kwargs):
        raise AssertionError("/think must not touch Drive")

    async def forbidden_brave_web_search(*args, **kwargs):
        raise AssertionError("/think must not touch web search")

    async def forbidden_create_github_issue(*args, **kwargs):
        raise AssertionError("/think must not touch GitHub")

    class FakeThinkLlm:
        def create_message(self, *, messages, system):
            assert "Не используйте веб" in system
            assert messages[0]["content"] == "Составь план запуска"
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Короткий ответ: Сделать dry-run.\nДопущения: данные доступны.\nСледующие шаги: проверить риски.",
                    }
                ]
            }

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", forbidden_upload_markdown)
    monkeypatch.setattr("mitra_app.main.brave_web_search", forbidden_brave_web_search)
    monkeypatch.setattr("mitra_app.main._create_github_issue", forbidden_create_github_issue)
    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeThinkLlm)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/think Составь план запуска", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(calls) == 1
    reply = calls[0][1]
    assert "Короткий ответ:" in reply
    assert "Допущения:" in reply
    assert "Следующие шаги:" in reply


def test_think_command_strips_thinking_tags_from_llm_reply(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")

    sent_payloads = []

    class FakeTelegramResponse:
        def raise_for_status(self):
            return None

    class FakeTelegramClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            sent_payloads.append(json)
            return FakeTelegramResponse()

    class FakeThinkLlm:
        def create_message(self, *, messages, system):
            return {"content": [{"type": "text", "text": "<thinking>hidden</thinking>\nPONG"}]}

    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeThinkLlm)
    monkeypatch.setattr("mitra_app.telegram.httpx.AsyncClient", lambda *args, **kwargs: FakeTelegramClient())

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/think ping", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert sent_payloads == [{"chat_id": 123, "text": "PONG"}]


def test_think_command_redacts_secret_assignments_and_limits_prompt(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    prompts = []

    class FakeThinkLlm:
        def create_message(self, *, messages, system):
            prompts.append(messages[0]["content"])
            return {"content": [{"type": "text", "text": "Короткий ответ: ok\nДопущения: ok\nСледующие шаги: ok"}]}

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeThinkLlm)

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
    assert len(prompts) == 1
    assert "12345" not in prompts[0]
    assert "[REDACTED]" in prompts[0]
    reply = calls[0][1]
    assert len(reply) <= 900


def test_think_command_without_text_returns_usage_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/think", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Usage: /think <вопрос/задача>")]
    event = [entry for entry in audits if entry.get("event") == "telegram_think"][0]
    assert event["action_id"].startswith("act-")
    assert event["user_id"] == 123
    assert event["command"] == "/think"
    assert event["outcome"] == "usage"


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
        assert "mitra drive check" in markdown_body
        return DriveUploadResult(file_id="file-123", web_view_link="https://drive.test/view")

    async def fake_trash_file(file_id: str):
        assert file_id == "file-123"
        return None

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.main.trash_file", fake_trash_file)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/drive_check", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == 123
    assert calls[0][1].startswith("Drive OK (auth=oauth) latency_ms=")
    assert "file_id=file-123 (deleted)" in calls[0][1]
    drive_check_audit = next(event for event in audits if event.get("event") == "drive_check")
    assert drive_check_audit == {
        "event": "drive_check",
        "user_id": 123,
        "chat_id": 123,
        "auth_mode": "oauth",
        "outcome": "success",
        "detail": "upload+trash ok",
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

    async def fake_upload_markdown(title: str, markdown_body: str):
        return DriveUploadResult(file_id="endpoint-file", web_view_link="https://drive.test/view")

    async def fake_trash_file(file_id: str):
        assert file_id == "endpoint-file"
        return None

    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.main.trash_file", fake_trash_file)

    response = client.get("/drive_check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "oauth"
    assert payload["status"].startswith("Drive OK (auth=oauth) latency_ms=")
    assert "file_id=endpoint-file (deleted)" in payload["status"]


def test_drive_check_endpoint_returns_specific_http_error(monkeypatch):
    monkeypatch.delenv("DRIVE_OAUTH_REFRESH_TOKEN", raising=False)

    class FakeResp:
        status = 403
        reason = "Forbidden"

    async def failing_upload(*args, **kwargs):
        raise HttpError(FakeResp(), b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}', uri="https://drive.test")

    monkeypatch.setattr("mitra_app.main.upload_markdown", failing_upload)

    response = client.get("/drive_check")

    assert response.status_code == 200
    assert response.json() == {
        "auth_mode": "service_account",
        "status": "Drive error: 403 insufficientPermissions",
    }


def test_drive_check_command_failure_still_returns_http_200(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/drive_check", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Drive error: unknown drive_check_failed")]
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


def test_smoke_command_formats_status_lines_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "folder-1")
    monkeypatch.setenv("DRIVE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("DRIVE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)
    monkeypatch.setattr("mitra_app.main.get_drive_auth_mode", lambda: "oauth")
    monkeypatch.setattr("mitra_app.main.get_last_oauth_refresh_time", lambda: "2026-01-01T00:00:00+00:00")

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/smoke", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls
    reply = calls[0][1]
    assert "- telegram: OK" in reply
    assert "- allowlist: OK" in reply
    assert "- oauth: OK (auth_mode=oauth, last_refresh_at=2026-01-01T00:00:00+00:00)" in reply
    assert "- drive: OK" in reply
    assert "- llm: OK" in reply
    assert "- search: OK" in reply
    smoke_audit = next(event for event in audits if event.get("event") == "telegram_smoke")
    assert smoke_audit["action_type"] == "/smoke"
    assert smoke_audit["outcome"] == "completed"


def test_smoke_deep_captures_failures_instead_of_raising(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_upload_markdown(title: str, markdown_body: str):
        raise RuntimeError("drive down")

    class FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_message(self, messages):
            raise RuntimeError("llm down")

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.upload_markdown", fake_upload_markdown)
    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeAnthropicClient)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/smoke_deep", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    reply = calls[0][1]
    assert "- drive_deep: FAIL" in reply
    assert "- llm_deep: FAIL" in reply
    assert "- search_deep: NA" in reply
    smoke_audit = next(event for event in audits if event.get("event") == "telegram_smoke_deep")
    assert smoke_audit["outcome"] == "completed"
    assert smoke_audit["checks"]["drive"]["status"] == "fail"
    assert smoke_audit["checks"]["llm"]["status"] == "fail"
    assert smoke_audit["checks"]["search"]["status"] == "na"


def test_start_help_lists_smoke_command(monkeypatch):
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
        json={"message": {"text": "/start", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert "/smoke" in calls[0][1]


def test_start_help_lists_pr_commands(monkeypatch):
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
        json={"message": {"text": "/start", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert "/pr <title>\\n<spec>" in calls[0][1]
    assert "/pr_status <issue#|pr#>" in calls[0][1]


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


def test_pr_command_creates_issue_with_mitra_codex_label_and_returns_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    @dataclass
    class FakeIssue:
        number: int
        html_url: str

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_create_issue(title: str, body: str, labels: list[str] | None = None):
        assert title == "Need better onboarding"
        assert body == "Step 1\nStep 2"
        assert labels == ["mitra:codex"]
        return FakeIssue(number=77, html_url="https://github.com/o/r/issues/77")

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/pr Need better onboarding\nStep 1\nStep 2",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    assert calls == [(123, "Created: https://github.com/o/r/issues/77")]

    pr_audit = next(event for event in audits if event.get("event") == "telegram_pr_open_issue")
    assert pr_audit["issue_number"] == 77
    assert pr_audit["outcome"] == "success"


def test_pr_command_denied_for_non_allowlisted_user(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    called = False

    async def fake_create_issue(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not be called")

    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/pr blocked\nspec", "chat": {"id": 123}, "from": {"id": 999}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert called is False


def test_pr_command_audits_error_when_github_create_fails(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_create_issue(title: str, body: str, labels: list[str] | None = None):
        raise RuntimeError("boom")

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/pr Broken\nSpec", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Failed to create issue")]

    pr_audit = next(event for event in audits if event.get("event") == "telegram_pr_open_issue")
    assert pr_audit["issue_number"] is None
    assert pr_audit["outcome"] == "error"


def test_task_command_creates_codex_issue_and_reports_expected_command(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_create_github_issue(title: str, body: str):
        assert title == "Добавить /hello"
        assert "## Acceptance criteria" in body
        assert "## Allowed file scope" in body
        return 88, "https://github.com/o/r/issues/88"

    def fake_build_task_spec(request_text: str):
        assert "/hello" in request_text
        return {
            "title": "Добавить /hello",
            "summary": "Добавить простую команду.",
            "components": ["mitra_app/main.py"],
            "required_env_secrets": ["OPENAI_API_KEY"],
            "new_commands": ["/hello"],
            "acceptance_criteria": ["Команда /hello отвечает hello from mitra"],
            "tests_to_add": ["pytest для /telegram/webhook"],
            "risk_level": "R1",
            "allowed_file_scope": ["mitra_app/*", "tests/*"],
        }

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/task Добавь /hello в GitHub, секреты в Vault, риск R1, команда должна отвечать hello, дедлайн 2026-01-10", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "Issue создан: https://github.com/o/r/issues/88" in calls[0][1]
    assert "Требуются ключи/доступы: OPENAI_API_KEY" in calls[0][1]
    assert "Ожидаемая новая команда: /hello" in calls[0][1]


def test_task_command_without_llm_json_uses_fallback_spec(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    class FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_message(self, messages, system):
            return {"content": [{"type": "text", "text": "Не JSON ответ"}]}

    async def fake_create_github_issue(title: str, body: str):
        assert "Добавь новую команду" in title
        assert "## Summary" in body
        assert "## Risk level\n- R2" in body
        assert "## Allowed file scope\n- mitra_app/*\n- tests/*" in body
        assert "Добавь новую команду" in body
        return 91, "https://github.com/o/r/issues/91"

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.AnthropicClient", FakeAnthropicClient)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/task Добавь новую команду в GitHub, секреты в env, риск R2, команда должна отвечать текущим временем и коротким статусом системы, дедлайн 2026-02-01",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "Issue создан: https://github.com/o/r/issues/91" in calls[0][1]
    assert "Spec auto-filled from request (LLM JSON parse failed)" in calls[0][1]

    task_audit = next(event for event in audits if event.get("event") == "telegram_task_open_issue")
    assert task_audit["action_type"] == "/task"
    assert task_audit["degraded"] is True
    assert task_audit["parse_outcome"] == "fallback"
    assert task_audit["issue_url"] == "https://github.com/o/r/issues/91"
    assert task_audit["risk_level"] == "R2"
    assert task_audit["allowed_file_scope"] == ["mitra_app/*", "tests/*"]


def test_task_command_without_body_returns_usage(monkeypatch):
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
        json={"message": {"text": "/task", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Usage: /task <request>")]


def test_task_command_multiturn_collects_context_before_issue_creation(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    _task_dialog_state_by_chat.clear()

    calls = []
    build_calls = []
    issue_calls = []
    detect_calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_detect_capability_gaps(request_text: str):
        detect_calls.append(request_text)
        return {
            "intents": ["hello"],
            "matched_capabilities": [],
            "gaps": ["code"],
            "coverage_status": "missing",
            "gap_closure_notes": ["code: capability отсутствует в каталоге — требуется явная реализация/описание."],
        }

    def fake_build_task_spec(request_text: str):
        build_calls.append(request_text)
        assert "- issue provider: GitHub" in request_text
        assert "- integration provider: Yandex" in request_text
        assert "- credentials source: я тебе дам в 1password" in request_text
        assert '- risk constraints: {"has_constraints": false, "details": []}' in request_text
        return {
            "title": "Добавить /hello",
            "summary": "Добавить простую команду.",
            "components": ["mitra_app/main.py"],
            "required_env_secrets": ["OPENAI_API_KEY"],
            "new_commands": ["/hello"],
            "acceptance_criteria": ["Команда /hello отвечает hello from mitra"],
            "tests_to_add": ["pytest для /telegram/webhook"],
            "risk_level": "R1",
        }

    async def fake_create_github_issue(title: str, body: str):
        issue_calls.append((title, body))
        return 101, "https://github.com/o/r/issues/101"

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)
    monkeypatch.setattr("mitra_app.main.detect_capability_gaps", fake_detect_capability_gaps)

    first = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/task Добавь /hello в GitHub, команда должна отвечать hello",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )
    second = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "яндекс", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    third = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "я тебе дам", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    fourth = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "я тебе дам в 1password", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    fifth = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "нет ограниченийъ", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    fourth = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "R1 only", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    fifth = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "Команда работает корректно", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    sixth = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "2026-01-10", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert fourth.status_code == 200
    assert fifth.status_code == 200
    assert calls[0] == (123, "Какой integration provider используется в задаче (например Yandex/Google/Outlook)?")
    assert calls[1] == (123, "Где брать credentials (источник секретов/доступов)?")
    assert calls[2] == (
        123,
        "Нужно чуть подробнее: где именно брать credentials. Где брать credentials (источник секретов/доступов)?",
    )
    assert calls[3] == (123, "Какие есть risk constraints (например max risk level, ограничения по данным/продакшену)?")
    assert "Issue создан: https://github.com/o/r/issues/101" in calls[4][1]
    assert len(build_calls) == 1
    assert len(issue_calls) == 1
    assert detect_calls == ["Добавь /hello, команда должна отвечать hello"]
    assert "Gap summary: missing capability, закрыть блоки: code" in calls[2][1]


def test_task_dialog_treats_slash_text_as_answer_until_required_fields_are_filled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    _task_dialog_state_by_chat.clear()

    calls = []
    issue_calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_build_task_spec(request_text: str):
        assert "- provider: /status" in request_text
        assert "- credentials source: Vault" in request_text
        assert "- risk constraints: R1 only" in request_text
        assert "- success criteria: /help" in request_text
        assert "- deadlines: 2026-02-10" in request_text
        return {
            "title": "Добавить /hello",
            "summary": "Добавить простую команду.",
            "components": ["mitra_app/main.py"],
            "required_env_secrets": [],
            "new_commands": ["/hello"],
            "acceptance_criteria": ["Команда /hello отвечает hello from mitra"],
            "tests_to_add": ["tests/test_telegram_webhook.py"],
            "risk_level": "R1",
        }

    async def fake_create_github_issue(title: str, body: str):
        issue_calls.append((title, body))
        return 102, "https://github.com/o/r/issues/102"

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)

    messages = [
        "/task Нужна новая команда",
        "/status",
        "Vault",
        "R1 only",
        "/help",
        "2026-02-10",
    ]
    for message in messages:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"message": {"text": message, "chat": {"id": 123}, "from": {"id": 123}}},
        )
        assert response.status_code == 200

    assert calls[0][1].startswith("Уточни provider")
    assert calls[1] == (123, "Где брать credentials (источник секретов/доступов)?")
    assert calls[2] == (123, "Какие есть risk constraints (например max risk level, ограничения по данным/продакшену)?")
    assert calls[3] == (123, "Сформулируй success criteria (как поймём, что задача выполнена).")
    assert calls[4] == (123, "Есть ли deadline/срок для задачи?")
    assert "Issue создан: https://github.com/o/r/issues/102" in calls[5][1]
    assert len(issue_calls) == 1
    assert 123 not in _task_dialog_state_by_chat


def test_task_dialog_does_not_fallback_unknown_command_while_active(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    _task_dialog_state_by_chat.clear()

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    start_response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/task Нужна новая команда", "chat": {"id": 123}, "from": {"id": 123}}},
    )
    slash_response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/unknown", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert start_response.status_code == 200
    assert slash_response.status_code == 200
    assert calls[0][1].startswith("Уточни provider")
    assert calls[1] == (123, "Где брать credentials (источник секретов/доступов)?")
    assert all(text != "Unknown command" for _, text in calls)


def test_build_task_spec_returns_fallback_when_json_parse_fails(caplog):
    class FakeClient:
        def create_message(self, *, messages, system):
            return {
                "content": [
                    {"type": "thinking", "thinking": "internal"},
                    {"type": "text", "text": "Not JSON. OPENAI_API_KEY=top-secret"},
                ]
            }

    with caplog.at_level(logging.WARNING, logger="mitra_app.main"):
        spec = _build_task_spec("Сделай команду /hello", llm_client=FakeClient())

    assert spec == {
        "title": "Сделай команду /hello",
        "summary": "Сделай команду /hello",
        "components": [],
        "required_env_secrets": [],
        "new_commands": [],
        "acceptance_criteria": [],
        "tests_to_add": [],
        "risk_level": "R2",
        "allowed_file_scope": ["mitra_app/*", "tests/*"],
        "degraded": True,
        "parse_outcome": "fallback",
    }

    assert "OPENAI_API_KEY=top-secret" not in caplog.text
    assert any(rec.message == "task_spec_fallback_used" for rec in caplog.records)


def test_build_task_spec_returns_fallback_when_multiple_non_json_text_blocks_returned(caplog):
    class FakeClient:
        def create_message(self, *, messages, system):
            return {
                "content": [
                    {"type": "text", "text": "still not json"},
                    {"type": "text", "text": "also not json"},
                ]
            }

    with caplog.at_level(logging.WARNING, logger="mitra_app.main"):
        spec = _build_task_spec("Нужен fallback", llm_client=FakeClient())

    assert spec["degraded"] is True
    assert spec["summary"] == "Нужен fallback"
    assert any(rec.message == "task_spec_fallback_used" for rec in caplog.records)


def test_detect_capability_gaps_for_new_capability_request_returns_all_required_blocks():
    detection = detect_capability_gaps("Нужна новая способность для партнёрской интеграции с CRM")

    assert detection["matched_capabilities"] == []
    assert detection["gaps"] == ["code", "policy", "config", "tests", "secrets", "runbook"]
    assert detection["coverage_status"] == "missing"
    assert all("capability отсутствует" in note for note in detection["gap_closure_notes"])


def test_task_command_includes_gap_sections_in_issue_body(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_create_github_issue(title: str, body: str):
        assert title == "Добавить новую способность CRM"
        assert "## Capability gaps to close" in body
        assert "### GAP: code" in body
        assert "### GAP: policy" in body
        assert "### GAP: config" in body
        assert "### GAP: tests" in body
        assert "### GAP: secrets" in body
        assert "### GAP: runbook" in body
        assert "capability отсутствует в каталоге" in body
        return 109, "https://github.com/o/r/issues/109"

    def fake_build_task_spec(request_text: str):
        assert "новую способность" in request_text
        return {
            "title": "Добавить новую способность CRM",
            "summary": "Нужно создать способность для CRM-синхронизации.",
            "components": [],
            "required_env_secrets": [],
            "new_commands": [],
            "acceptance_criteria": ["Способность документирована и интегрирована"],
            "tests_to_add": [],
            "risk_level": "R2",
        }

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/task Добавить новую способность CRM с синхронизацией в Jira, секреты в env, риск R2, команда должна отдавать статус CRM, дедлайн 2026-02-10",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "Issue создан: https://github.com/o/r/issues/109" in calls[0][1]
    assert "Обнаружены gaps: code, policy, config, tests, secrets, runbook" in calls[0][1]
    assert "Gap summary: missing capability, закрыть блоки: code, policy, config, tests, secrets, runbook" in calls[0][1]


def test_detect_capability_gaps_for_calendar_management_request_returns_calendar_artifact_gaps():
    detection = detect_capability_gaps("Нужно управлять календарём: перенос встреч и проверка доступности команды")

    assert detection["matched_capabilities"] == ["calendar"]
    assert detection["gaps"] == ["code", "tests", "runbook"]


def test_task_command_calendar_logs_detected_gaps_and_capabilities(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_create_github_issue(title: str, body: str):
        assert title == "Calendar sync hardening"
        assert "## Capability gaps to close" in body
        assert "### GAP: code" in body
        assert "### GAP: tests" in body
        assert "### GAP: runbook" in body
        assert "capability частично реализована (calendar)" in body
        return 120, "https://github.com/o/r/issues/120"

    def fake_build_task_spec(request_text: str):
        assert "calendar" in request_text.lower()
        return {
            "title": "Calendar sync hardening",
            "summary": "Улучшить обработку calendar webhooks.",
            "components": ["mitra_app/main.py"],
            "required_env_secrets": [],
            "new_commands": [],
            "acceptance_criteria": ["Calendar workflow стабилен"],
            "tests_to_add": ["tests/test_telegram_webhook.py"],
            "risk_level": "R2",
            "allowed_file_scope": ["mitra_app/*", "tests/*"],
        }

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._build_task_spec", fake_build_task_spec)
    monkeypatch.setattr("mitra_app.main._create_github_issue", fake_create_github_issue)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "message": {
                "text": "/task Improve calendar sync in Jira, secrets in env, risk R2, acceptance criteria: no duplicate meetings, deadline 2026-03-01",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "Обнаружены gaps: tests, secrets, runbook" in calls[0][1]
    assert "Gap summary: partial capability, закрыть блоки: tests, secrets, runbook" in calls[0][1]

    task_audit = next(event for event in audits if event.get("event") == "telegram_task_open_issue")
    assert task_audit["request_intents"]
    assert task_audit["matched_capabilities"] == ["calendar"]
    assert task_audit["detected_gaps"] == ["tests", "secrets", "runbook"]
    assert task_audit["parse_outcome"] == "primary"
    assert task_audit["dialog_state"] is None




def test_unknown_command_audits_reason_code_and_dialog_state(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/unknown_command", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Unknown command")]

    unknown_audit = next(event for event in audits if event.get("event") == "telegram_unknown_command")
    assert unknown_audit["reason_code"] == "unknown_command"
    assert unknown_audit["dialog_state"] is None

def test_extract_json_object_handles_dirty_text_with_fenced_block_and_json():
    dirty = """Ниже набросок ответа.
```text
Это не JSON
```
```json
{"title":"Dirty JSON title", "risk_level":"R1"}
```
Хвостовой текст.
"""

    parsed = _extract_json_object(dirty)

    assert parsed == {"title": "Dirty JSON title", "risk_level": "R1"}


def test_github_actions_callback_posts_to_admin_chat(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS_CALLBACK_TOKEN", "cb-secret")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "777")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)

    response = client.post(
        "/github/actions_callback",
        headers={"X-Mitra-Actions-Token": "cb-secret"},
        json={
            "event": "pr_opened",
            "issue_number": 55,
            "pr_number": 144,
            "pr_url": "https://github.com/o/r/pull/144",
        },
    )

    assert response.status_code == 200
    assert calls == [(777, "PR открыт: #144 (issue #55)\nhttps://github.com/o/r/pull/144")]


def test_github_actions_callback_failed_ci_logs_gap_and_updates_backlog(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS_CALLBACK_TOKEN", "cb-secret")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "777")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_poll(pr_number: int):
        from mitra_app.github import GitHubChecksSummary, GitHubPullRequestStatus

        return (
            "failed",
            "pytest failure",
            GitHubPullRequestStatus(
                number=pr_number,
                state="open",
                draft=False,
                merged=False,
                mergeable=True,
                head_sha="abc",
                html_url=f"https://github.com/o/r/pull/{pr_number}",
            ),
            GitHubChecksSummary(total=2, successful=1, failed=1, pending=0),
        )

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._poll_pr_ci_snapshot", fake_poll)

    response = client.post(
        "/github/actions_callback",
        headers={"X-Mitra-Actions-Token": "cb-secret"},
        json={"event": "ci_failed", "pr_number": 145},
    )

    assert response.status_code == 200
    assert calls and "Gap: tests_missing" in calls[0][1]

    backlog = (tmp_path / "reports" / "capability_gaps.md").read_text(encoding="utf-8")
    assert "#145" in backlog
    assert "tests_missing" in backlog

    audit_lines = (tmp_path / "events.ndjson").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(audit_lines[-1])
    assert payload["event"] == "github_pr_ci_status"
    assert payload["failure_reason"] == "pytest failure"
    assert payload["gap_type"] == "tests_missing"


def test_github_actions_callback_repeated_failure_suggests_task_template(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS_CALLBACK_TOKEN", "cb-secret")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "777")
    monkeypatch.setenv("MITRA_AUDIT_LOG", str(tmp_path / "events.ndjson"))

    (tmp_path / "events.ndjson").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-02-25T10:00:00+00:00",
                        "event": "github_pr_ci_status",
                        "outcome": "failed",
                        "gap_type": "env_missing",
                        "pr_number": 99,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-02-25T11:00:00+00:00",
                        "event": "github_pr_ci_status",
                        "outcome": "failed",
                        "gap_type": "env_missing",
                        "pr_number": 99,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_poll(pr_number: int):
        from mitra_app.github import GitHubChecksSummary, GitHubPullRequestStatus

        return (
            "failed",
            "missing secret",
            GitHubPullRequestStatus(
                number=pr_number,
                state="open",
                draft=False,
                merged=False,
                mergeable=True,
                head_sha="abc",
                html_url=f"https://github.com/o/r/pull/{pr_number}",
            ),
            GitHubChecksSummary(total=1, successful=0, failed=1, pending=0),
        )

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._poll_pr_ci_snapshot", fake_poll)

    response = client.post(
        "/github/actions_callback",
        headers={"X-Mitra-Actions-Token": "cb-secret"},
        json={"event": "ci_failed", "pr_number": 99},
    )

    assert response.status_code == 200
    assert calls
    assert "Повторяющийся провал" in calls[0][1]
    assert "/task Root-cause fix" in calls[0][1]

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



def test_research_unexpected_error_is_sanitized(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    async def fake_run_research(query: str):
        raise RuntimeError("boom\nTraceback: internal")

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main.run_research", fake_run_research)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/research ai agents", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Research failed: boom Traceback: internal")]
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



def test_command_policies_cover_supported_webhook_commands():
    supported_action_types = {
        "/status",
        "/smoke_deep",
        "/smoke",
        "/oauth_status",
        "/whoami",
        "/search",
        "/llm_check",
        "/goal",
        "/goal set",
        "/think",
        "/reflect",
        "/reports",
        "/research",
        "/report",
        "/pr_status",
        "/task",
        "/pr",
        "/evo_issue",
        "/drive_check",
        "/budget_reset_day",
        "/budget",
        "/help",
        "/start",
    }

    assert supported_action_types == set(_COMMAND_POLICIES)

    help_commands = {token for token in HELP_TEXT.split() if token.startswith("/")}
    normalized_help_commands = {token.split("\n")[0].rstrip(",") for token in help_commands}
    assert normalized_help_commands <= supported_action_types


@pytest.mark.parametrize(
    "text",
    [
        "/search ai",
        "/research ai",
        "/pr Title\nSpec",
        "/think plan",
        "/goal set Improve MTTR",
        "/llm_check",
        "/evo_issue 1",
        "/budget_reset_day",
    ],
)
def test_policy_denies_synced_commands_before_handler(monkeypatch, text):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_enforce(*, current_al: str, policy):
        return type("Decision", (), {"allowed": False, "reason": "Denied: requires AL2/R2"})()

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._policy_enforcer.enforce", fake_enforce)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": text, "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, "Denied: requires AL2/R2")]


@pytest.mark.parametrize(
    ("text", "expected_reply"),
    [
        ("/search ai", "Search not configured"),
        ("/research", "Usage: /research <query>"),
        ("/pr", "Usage: /pr <title>\n<spec>"),
        ("/evo_issue", "Usage: /evo_issue <n> [risk:R0-R3]"),
        ("/budget_reset_day", "Forbidden"),
    ],
)
def test_policy_allows_synced_commands(monkeypatch, text, expected_reply):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    calls = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_enforce(*, current_al: str, policy):
        return type("Decision", (), {"allowed": True, "reason": None})()

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._policy_enforcer.enforce", fake_enforce)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": text, "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert calls == [(123, expected_reply)]


def test_policy_enforcement_exception_never_crashes_webhook(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    calls = []
    audits = []

    async def fake_send_message(chat_id: int, text: str):
        calls.append((chat_id, text))
        return True

    def fake_enforce(*, current_al: str, policy):
        raise RuntimeError("boom")

    def fake_log_event(event: dict[str, object]):
        audits.append(event)

    monkeypatch.setattr("mitra_app.main.send_message", fake_send_message)
    monkeypatch.setattr("mitra_app.main._policy_enforcer.enforce", fake_enforce)
    monkeypatch.setattr("mitra_app.audit.log_event", fake_log_event)

    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={"message": {"text": "/report test", "chat": {"id": 123}, "from": {"id": 123}}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [(123, "Denied: requires AL2/R2")]
    denial = [event for event in audits if event.get("event") == "telegram_policy_denied"][0]
    assert denial["action_type"] == "/report"
    assert denial["required_al"] == "AL2"
    assert denial["risk_level"] == "R2"
    assert denial["outcome"] == "denied"


def test_parse_pr_or_issue_ref_supports_issue_and_pr_forms():
    assert _parse_pr_or_issue_ref("42") == ("issue", 42)
    assert _parse_pr_or_issue_ref("#42") == ("issue", 42)
    assert _parse_pr_or_issue_ref("https://github.com/o/r/issues/42") == ("issue", 42)
    assert _parse_pr_or_issue_ref("pr#42") == ("pr", 42)
    assert _parse_pr_or_issue_ref("https://github.com/o/r/pull/42") == ("pr", 42)
    assert _parse_pr_or_issue_ref("not-a-number") is None


def test_build_pr_status_reply_accepts_pr_reference(monkeypatch):
    @dataclass
    class FakePrStatus:
        number: int
        state: str
        draft: bool
        merged: bool | None
        mergeable: bool | None
        head_sha: str
        html_url: str

    @dataclass
    class FakeChecks:
        total: int
        successful: int
        failed: int
        pending: int

    async def forbidden_find_linked_pr(*args, **kwargs):
        raise AssertionError("find_linked_pr should not be called for PR references")

    async def fake_get_pr_status(number: int):
        assert number == 84
        return FakePrStatus(
            number=84,
            state="open",
            draft=False,
            merged=False,
            mergeable=True,
            head_sha="abc123",
            html_url="https://github.com/o/r/pull/84",
        )

    async def fake_get_pr_checks_summary(head_sha: str):
        assert head_sha == "abc123"
        return FakeChecks(total=3, successful=2, failed=1, pending=0)

    monkeypatch.setattr("mitra_app.main.github.find_linked_pr", forbidden_find_linked_pr)
    monkeypatch.setattr("mitra_app.main.github.get_pr_status", fake_get_pr_status)
    monkeypatch.setattr("mitra_app.main.github.get_pr_checks_summary", fake_get_pr_checks_summary)

    reply = asyncio.run(_build_pr_status_reply("pr#84"))

    assert reply == (
        "PR: https://github.com/o/r/pull/84\n"
        "State: open\n"
        "Checks: total=3, success=2, failed=1, pending=0"
    )
