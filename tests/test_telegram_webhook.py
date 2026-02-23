from fastapi.testclient import TestClient

from mitra_app.main import app


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
