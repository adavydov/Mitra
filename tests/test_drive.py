import asyncio

import pytest
from mitra_app.drive import DriveNotConfigured, upload_markdown


def test_upload_markdown_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("DRIVE_ROOT_FOLDER_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)

    with pytest.raises(DriveNotConfigured):
        asyncio.run(upload_markdown("Report", "# hello"))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, headers, files):
        assert "uploadType=multipart" in url
        assert headers["Authorization"] == "Bearer token"
        assert files["file"][2] == "text/markdown"
        return _FakeResponse({"id": "file-123"})

    async def get(self, url, headers):
        assert url.endswith("?fields=webViewLink")
        assert headers["Authorization"] == "Bearer token"
        return _FakeResponse({"webViewLink": "https://drive/link"})


def test_upload_markdown_returns_file_id_and_link(monkeypatch):
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "root-folder")
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "token")
    monkeypatch.setattr("mitra_app.drive.httpx.AsyncClient", lambda timeout: _FakeAsyncClient())

    result = asyncio.run(upload_markdown("Daily Report", "# Content"))

    assert result.file_id == "file-123"
    assert result.web_view_link == "https://drive/link"
