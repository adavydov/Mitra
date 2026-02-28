import json

from mitra_app.audit import _redact_value, log_event, log_report_event


def test_log_event_redacts_known_env_vars(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-456")

    line = log_event(
        {
            "message": "using token-123 and secret-456",
            "api_key": "abc",
            "nested": {"public": "ok", "privateKey": "xyz"},
        }
    )

    payload = json.loads(line)
    assert payload["message"] == "using [REDACTED] and [REDACTED]"
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["privateKey"] == "[REDACTED]"

    written = (tmp_path / "audit" / "events.ndjson").read_text(encoding="utf-8").strip()
    assert "token-123" not in written
    assert "secret-456" not in written

    stdout = capsys.readouterr().out.strip()
    assert stdout == written


def test_log_event_redacts_drive_keys_and_pem(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON", '{"private_key":"pem-value"}')
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON_B64", "b64-value")

    line = log_event(
        {
            "credentials": "b64-value",
            "service_account": '{"private_key":"pem-value"}',
            "pem_block": "-----BEGIN PRIVATE KEY-----\nabc",
        }
    )

    payload = json.loads(line)
    assert payload["credentials"] == "[REDACTED]"
    assert payload["service_account"] == "[REDACTED]"
    assert payload["pem_block"] == "[REDACTED]"

    written = (tmp_path / "audit" / "events.ndjson").read_text(encoding="utf-8").strip()
    assert "b64-value" not in written
    assert "pem-value" not in written
    assert "-----BEGIN" not in written


def test_log_report_event_does_not_raise_when_file_write_fails(monkeypatch):
    def failing_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", failing_open)

    log_report_event(
        action_id="act-1",
        user_id=123,
        chat_id=456,
        file_id="",
        outcome="error",
    )


def test_redact_value_masks_long_credential_like_strings():
    token = "ghp_" + "A" * 36
    value = _redact_value({"note": f"token={token}"})

    assert isinstance(value, dict)
    assert value["note"] == "token=[REDACTED]"


def test_log_event_redacts_jwt_like_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    jwt_like = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signatureVALUE123456789"

    line = log_event({"metadata": f"oauth token: {jwt_like}"})

    payload = json.loads(line)
    assert "[REDACTED]" in payload["metadata"]
    assert jwt_like not in payload["metadata"]

