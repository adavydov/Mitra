from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx


class DriveNotConfiguredError(RuntimeError):
    """Raised when Drive integration is not configured."""


@dataclass
class DriveUploadResult:
    file_id: str
    web_view_link: str | None


def _require_drive_config() -> tuple[str, str]:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    access_token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    if not folder_id or not access_token:
        raise DriveNotConfiguredError("Drive is not configured")
    return folder_id, access_token


async def upload_markdown_document(title: str, markdown_body: str) -> DriveUploadResult:
    folder_id, access_token = _require_drive_config()

    metadata = {
        "name": f"{title}.md",
        "parents": [folder_id],
        "mimeType": "text/markdown",
    }

    files = {
        "metadata": (None, json.dumps(metadata), "application/json"),
        "file": (f"{title}.md", markdown_body, "text/markdown"),
    }

    headers = {"Authorization": f"Bearer {access_token}"}
    create_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"

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
