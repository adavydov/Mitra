from __future__ import annotations

import base64
import json
import os
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

class DriveNotConfigured(RuntimeError):
    """Raised when Drive integration is not configured."""

class DriveNotConfigured(RuntimeError):
    """Raised when Google Drive integration is missing required configuration."""

DriveNotConfiguredError = DriveNotConfigured


@dataclass
class DriveUploadResult:
    file_id: str
    web_view_link: str | None

def _load_service_account_info() -> dict[str, Any]:
    payload_b64 = os.getenv("DRIVE_SERVICE_ACCOUNT_JSON_B64")
    payload_raw = os.getenv("DRIVE_SERVICE_ACCOUNT_JSON")

    if payload_b64:
        try:
            decoded = base64.b64decode(payload_b64).decode("utf-8")
            return json.loads(decoded)
        except Exception as exc:  # pragma: no cover - defensive path
            raise DriveNotConfigured("Invalid DRIVE_SERVICE_ACCOUNT_JSON_B64") from exc

    if payload_raw:
        try:
            return json.loads(payload_raw)
        except Exception as exc:  # pragma: no cover - defensive path
            raise DriveNotConfigured("Invalid DRIVE_SERVICE_ACCOUNT_JSON") from exc

    raise DriveNotConfigured("Missing service account credentials")


def _build_drive_service(credentials_info: dict[str, Any]):
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=[_DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)

def _require_drive_config() -> tuple[str, str]:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    access_token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    if not folder_id or not access_token:
        raise DriveNotConfigured("Drive is not configured")
    return folder_id, access_token

def upload_markdown(title: str, markdown: str) -> dict[str, str | None]:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not folder_id:
        raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

async def upload_markdown(title: str, markdown_body: str) -> DriveUploadResult:
    folder_id, access_token = _require_drive_config()

    metadata = {
        "name": title,
        "parents": [folder_id],
        "mimeType": "text/markdown",
    }
    media = MediaInMemoryUpload(markdown.encode("utf-8"), mimetype="text/markdown", resumable=False)

    response = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,webViewLink")
        .execute()
    )

    async with httpx.AsyncClient(timeout=20) as client:
        create_response = await client.post(create_url, headers=headers, files=files)
        create_response.raise_for_status()
        file_id = create_response.json().get("id", "")

        web_view_link = None
        if file_id:
            get_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=webViewLink"
            read_response = await client.get(get_url, headers=headers)
            read_response.raise_for_status()
            web_view_link = read_response.json().get("webViewLink")

    return DriveUploadResult(file_id=file_id, web_view_link=web_view_link)


async def upload_markdown_document(title: str, markdown_body: str) -> DriveUploadResult:
    """Backward-compatible alias for older call sites."""
    return await upload_markdown(title=title, markdown_body=markdown_body)
