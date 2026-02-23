import base64
import json

import pytest
from mitra_app.drive import DriveNotConfigured, upload_markdown


class _FakeCreateRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _FakeFilesResource:
    def __init__(self, sink, response):
        self.sink = sink
        self.response = response

    def create(self, **kwargs):
        self.sink.update(kwargs)
        return _FakeCreateRequest(self.response)


class _FakeDriveService:
    def __init__(self, sink, response):
        self.sink = sink
        self.response = response

    def files(self):
        return _FakeFilesResource(self.sink, self.response)


def test_upload_markdown_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("DRIVE_ROOT_FOLDER_ID", raising=False)
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON_B64", raising=False)

    with pytest.raises(DriveNotConfigured):
        upload_markdown("Report", "# hello")


def test_upload_markdown_uses_raw_json_env(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv(
        "DRIVE_SERVICE_ACCOUNT_JSON",
        json.dumps({"type": "service_account", "client_email": "bot@example.com"}),
    )

    captured = {}

    def fake_build_drive_service(credentials_info):
        assert credentials_info["client_email"] == "bot@example.com"
        return _FakeDriveService(captured, {"id": "file-123", "webViewLink": "https://drive/link"})

    monkeypatch.setattr("mitra_app.drive._build_drive_service", fake_build_drive_service)

    result = upload_markdown("Daily Report", "# Content")

    assert result == {"file_id": "file-123", "webViewLink": "https://drive/link"}
    assert captured["body"] == {
        "name": "Daily Report",
        "parents": ["root-folder"],
        "mimeType": "text/markdown",
    }
    assert hasattr(captured["media_body"], "getbytes")
    assert captured["media_body"].getbytes(0, len(b"# Content")) == b"# Content"
    assert captured["fields"] == "id,webViewLink"


def test_upload_markdown_uses_base64_env(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    payload = base64.b64encode(
        json.dumps({"type": "service_account", "client_email": "base64@example.com"}).encode("utf-8")
    ).decode("utf-8")
    monkeypatch.setenv("DRIVE_SERVICE_ACCOUNT_JSON_B64", payload)
    monkeypatch.delenv("DRIVE_SERVICE_ACCOUNT_JSON", raising=False)

    def fake_build_drive_service(credentials_info):
        assert credentials_info["client_email"] == "base64@example.com"
        return _FakeDriveService({}, {"id": "file-456"})

    monkeypatch.setattr("mitra_app.drive._build_drive_service", fake_build_drive_service)

    result = upload_markdown("Another Report", "markdown")

    assert result == {"file_id": "file-456", "webViewLink": None}
