import asyncio
import base64
import json

import pytest
from mitra_app.drive import DriveNotConfigured, upload_markdown


def _service_account_payload() -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": "demo",
        "private_key_id": "abc",
        "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        "client_email": "bot@example.iam.gserviceaccount.com",
        "client_id": "123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_upload_markdown_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("DRIVE_ROOT_FOLDER_ID", raising=False)
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON_B64", raising=False)
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON", raising=False)

    with pytest.raises(DriveNotConfigured):
        asyncio.run(upload_markdown("Report", "# hello"))


def test_upload_markdown_uses_b64_service_account_and_returns_link(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv(
        "DRIVE_SERVICE_ACCOUNT_JSON_B64",
        base64.b64encode(json.dumps(_service_account_payload()).encode("utf-8")).decode("utf-8"),
    )

    captured: dict[str, object] = {}

    class _FakeFilesResource:
        def create(self, body, media_body, fields):
            captured["body"] = body
            captured["fields"] = fields
            mime_value = getattr(media_body, "mimetype", None)
            captured["mime"] = mime_value() if callable(mime_value) else mime_value
            return self

        def execute(self):
            return {"id": "file-123", "webViewLink": "https://drive/link"}

    class _FakeService:
        def files(self):
            return _FakeFilesResource()

    def _fake_from_service_account_info(info, scopes):
        captured["info"] = info
        captured["scopes"] = scopes
        return object()

    monkeypatch.setattr("mitra_app.drive.service_account.Credentials.from_service_account_info", _fake_from_service_account_info)
    monkeypatch.setattr("mitra_app.drive.build", lambda *args, **kwargs: _FakeService())

    result = asyncio.run(upload_markdown("Daily Report", "# Content"))

    assert result.file_id == "file-123"
    assert result.web_view_link == "https://drive/link"
    assert captured["body"] == {
        "name": "Daily Report",
        "parents": ["root-folder"],
        "mimeType": "text/markdown",
    }
    assert captured["fields"] == "id,webViewLink"
    assert captured["mime"] == "text/markdown"
    assert captured["scopes"] == ["https://www.googleapis.com/auth/drive.file"]


def test_upload_markdown_falls_back_to_raw_json_env(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON_B64", raising=False)
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON", json.dumps(_service_account_payload()))

    class _FakeFilesResource:
        def create(self, body, media_body, fields):
            return self

        def execute(self):
            return {"id": "file-raw"}

    class _FakeService:
        def files(self):
            return _FakeFilesResource()

    monkeypatch.setattr(
        "mitra_app.drive.service_account.Credentials.from_service_account_info",
        lambda info, scopes: object(),
    )
    monkeypatch.setattr("mitra_app.drive.build", lambda *args, **kwargs: _FakeService())

    result = asyncio.run(upload_markdown("Daily Report", "# Content"))

    assert result.file_id == "file-raw"
    assert result.web_view_link is None
