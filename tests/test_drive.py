import asyncio
import base64
import json

import pytest
from mitra_app.drive import DriveNotConfigured, list_recent_files, upload_markdown


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


def test_upload_markdown_prefers_oauth_when_refresh_token_present(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("DRIVE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("DRIVE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON", "not-json")

    captured: dict[str, object] = {}

    class _FakeFilesResource:
        def create(self, body, media_body, fields):
            return self

        def execute(self):
            return {"id": "oauth-file"}

    class _FakeService:
        def files(self):
            return _FakeFilesResource()

    def _fake_oauth_credentials(*args, **kwargs):
        captured["oauth_kwargs"] = kwargs
        return object()

    def _unexpected_service_account(*args, **kwargs):
        raise AssertionError("service account credentials should be ignored when OAuth refresh token exists")

    monkeypatch.setattr("mitra_app.drive.OAuthCredentials", _fake_oauth_credentials)
    monkeypatch.setattr("mitra_app.drive.service_account.Credentials.from_service_account_info", _unexpected_service_account)
    monkeypatch.setattr("mitra_app.drive.build", lambda *args, **kwargs: _FakeService())

    result = asyncio.run(upload_markdown("Daily Report", "# Content"))

    assert result.file_id == "oauth-file"
    assert captured["oauth_kwargs"]["refresh_token"] == "refresh-token"


def test_upload_markdown_oauth_requires_client_credentials(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv("DRIVE_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.delenv("DRIVE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DRIVE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON", json.dumps(_service_account_payload()))

    with pytest.raises(DriveNotConfigured, match="Missing OAuth credentials"):
        asyncio.run(upload_markdown("Report", "# hello"))



def test_list_recent_files_uses_drive_query_and_limit(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv(
        "DRIVE_SERVICE_ACCOUNT_JSON_B64",
        base64.b64encode(json.dumps(_service_account_payload()).encode("utf-8")).decode("utf-8"),
    )

    captured: dict[str, object] = {}

    class _FakeFilesResource:
        def list(self, **kwargs):
            captured.update(kwargs)
            return self

        def execute(self):
            return {
                "files": [
                    {"id": "f1", "name": "One", "webViewLink": "https://drive/1"},
                    {"id": "f2", "name": "Two"},
                ]
            }

    class _FakeService:
        def files(self):
            return _FakeFilesResource()

    monkeypatch.setattr(
        "mitra_app.drive.service_account.Credentials.from_service_account_info",
        lambda info, scopes: object(),
    )
    monkeypatch.setattr("mitra_app.drive.build", lambda *args, **kwargs: _FakeService())

    results = asyncio.run(list_recent_files(limit=5))

    assert [f.file_id for f in results] == ["f1", "f2"]
    assert captured["q"] == "'root-folder' in parents and trashed = false"
    assert captured["pageSize"] == 5
    assert captured["orderBy"] == "modifiedTime desc"
    assert captured["supportsAllDrives"] is True
    assert captured["includeItemsFromAllDrives"] is True


def test_list_recent_files_adds_shared_drive_parameters(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv("DRIVE_SHARED_DRIVE_ID", "shared-123")
    monkeypatch.setenv(
        "DRIVE_SERVICE_ACCOUNT_JSON_B64",
        base64.b64encode(json.dumps(_service_account_payload()).encode("utf-8")).decode("utf-8"),
    )

    captured: dict[str, object] = {}

    class _FakeFilesResource:
        def list(self, **kwargs):
            captured.update(kwargs)
            return self

        def execute(self):
            return {"files": []}

    class _FakeService:
        def files(self):
            return _FakeFilesResource()

    monkeypatch.setattr(
        "mitra_app.drive.service_account.Credentials.from_service_account_info",
        lambda info, scopes: object(),
    )
    monkeypatch.setattr("mitra_app.drive.build", lambda *args, **kwargs: _FakeService())

    asyncio.run(list_recent_files(limit=5))

    assert captured["corpora"] == "drive"
    assert captured["driveId"] == "shared-123"
