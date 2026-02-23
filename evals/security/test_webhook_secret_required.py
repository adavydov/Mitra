from mitra_app.main import handle_telegram_webhook


def test_webhook_requires_secret(monkeypatch):
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', 'abc123')
    payload = {"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/status"}}
    status, body = handle_telegram_webhook(payload, secret_header=None)
    assert status in (401, 403)
    assert body["detail"] == "invalid_secret"
