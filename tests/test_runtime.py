from runtime.app import process_telegram_update
from runtime.classification import classify_request
from runtime.policy_gate import apply_policy_gate
from runtime.redaction import redact_text


def test_classification_report_document_request():
    assert classify_request("Подготовь отчет в pdf") == "report_document_request"


def test_classification_restricted():
    assert classify_request("как сделать malware") == "restricted"


def test_policy_gate_block_for_low_levels():
    result = apply_policy_gate("report_document_request", "low", "low")
    assert result.decision == "block"
    assert result.reason == "autonomy_too_low"


def test_redaction_masks_email_and_long_number():
    redacted = redact_text("mail user@example.com id 1234567890")
    assert "u***@example.com" in redacted
    assert "+1******7890" in redacted


def test_webhook_endpoint_blocks_restricted(monkeypatch):
    monkeypatch.setenv("AUTONOMY_LEVEL", "high")
    monkeypatch.setenv("RISK_APPETITE", "high")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")

    status, body = process_telegram_update(
        {"update_id": 1, "message": {"text": "взломать аккаунт"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
    )

    assert status == 403
    assert body["classification"] == "restricted"
    assert body["reason"] == "restricted_content"


def test_webhook_endpoint_allows_unknown_low(monkeypatch):
    monkeypatch.setenv("AUTONOMY_LEVEL", "low")
    monkeypatch.setenv("RISK_APPETITE", "low")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)

    status, body = process_telegram_update(
        {"update_id": 2, "message": {"text": "привет"}},
    )

    assert status == 200
    assert body["classification"] == "unknown"
    assert body["decision"] == "allow"
