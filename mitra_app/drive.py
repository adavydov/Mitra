from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from typing import Any

from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveNotConfigured(RuntimeError):
    """Raised when Google Drive integration is missing required configuration."""


DriveNotConfiguredError = DriveNotConfigured


def get_drive_auth_mode() -> str:
    return "oauth" if os.getenv("DRIVE_OAUTH_REFRESH_TOKEN") else "service_account"


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
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DriveNotConfigured("Invalid DRIVE_SERVICE_ACCOUNT_JSON_B64") from exc

    if payload_raw:
        try:
            return json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise DriveNotConfigured("Invalid DRIVE_SERVICE_ACCOUNT_JSON") from exc

    raise DriveNotConfigured("Missing service account credentials")


def _build_drive_service(credentials_info: dict[str, Any]):
    if get_drive_auth_mode() == "oauth":
        client_id = os.getenv("DRIVE_OAUTH_CLIENT_ID")
        client_secret = os.getenv("DRIVE_OAUTH_CLIENT_SECRET")
        refresh_token = os.getenv("DRIVE_OAUTH_REFRESH_TOKEN")
        token_uri = os.getenv("DRIVE_OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token")

        if not client_id or not client_secret or not refresh_token:
            raise DriveNotConfigured("Missing OAuth credentials")

        credentials = OAuthCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[_DRIVE_SCOPE],
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=[_DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


async def upload_markdown(title: str, markdown_body: str) -> DriveUploadResult:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not folder_id:
        raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

    credentials_info = {}
    if get_drive_auth_mode() == "service_account":
        credentials_info = _load_service_account_info()
    service = _build_drive_service(credentials_info)

    metadata = {
        "name": title,
        "parents": [folder_id],
        "mimeType": "text/markdown",
    }
    media = MediaInMemoryUpload(markdown_body.encode("utf-8"), mimetype="text/markdown", resumable=False)

    response = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,webViewLink")
        .execute()
    )

    return DriveUploadResult(
        file_id=response.get("id", ""),
        web_view_link=response.get("webViewLink"),
    )


async def upload_markdown_document(title: str, markdown_body: str) -> DriveUploadResult:
    """Backward-compatible alias for older call sites."""
    return await upload_markdown(title=title, markdown_body=markdown_body)
