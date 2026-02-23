from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveNotConfigured(RuntimeError):
    """Raised when Google Drive integration is missing required configuration."""


DriveNotConfiguredError = DriveNotConfigured
logger = logging.getLogger(__name__)
_last_oauth_refresh_at: datetime | None = None


class OAuthRefreshInvalidGrant(RuntimeError):
    """Raised when OAuth refresh token is no longer valid."""


def get_drive_auth_mode() -> str:
    return "oauth" if os.getenv("DRIVE_OAUTH_REFRESH_TOKEN") else "service_account"


def get_last_oauth_refresh_time() -> str | None:
    if _last_oauth_refresh_at is None:
        return None
    return _last_oauth_refresh_at.isoformat()


def _record_oauth_refresh_time() -> None:
    global _last_oauth_refresh_at
    _last_oauth_refresh_at = datetime.now(timezone.utc)


def _is_invalid_grant(exc: RefreshError) -> bool:
    message = str(exc).lower()
    return "invalid_grant" in message


@dataclass
class DriveUploadResult:
    file_id: str
    web_view_link: str | None


@dataclass
class DriveFile:
    file_id: str
    name: str
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

        try:
            credentials.refresh(Request())
            _record_oauth_refresh_time()
            logger.info("drive_oauth_refresh_success", extra={"last_refresh_at": get_last_oauth_refresh_time()})
        except RefreshError as exc:
            if _is_invalid_grant(exc):
                logger.warning("drive_oauth_refresh_invalid_grant")
                raise OAuthRefreshInvalidGrant("OAuth expired. Re-authorize required.") from exc
            raise

        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=[_DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


async def check_drive_folder_access() -> None:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not folder_id:
        raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

    credentials_info = {}
    if get_drive_auth_mode() == "service_account":
        credentials_info = _load_service_account_info()
    service = _build_drive_service(credentials_info)

    service.files().get(
        fileId=folder_id,
        fields="id",
        supportsAllDrives=True,
    ).execute()


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


async def delete_file(file_id: str) -> None:
    credentials_info = {}
    if get_drive_auth_mode() == "service_account":
        credentials_info = _load_service_account_info()
    service = _build_drive_service(credentials_info)
    service.files().delete(fileId=file_id).execute()


async def trash_file(file_id: str) -> None:
    credentials_info = {}
    if get_drive_auth_mode() == "service_account":
        credentials_info = _load_service_account_info()
    service = _build_drive_service(credentials_info)
    service.files().update(fileId=file_id, body={"trashed": True}, supportsAllDrives=True).execute()


async def list_recent_files(limit: int = 5) -> list[DriveFile]:
    folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not folder_id:
        raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

    credentials_info = {}
    if get_drive_auth_mode() == "service_account":
        credentials_info = _load_service_account_info()
    service = _build_drive_service(credentials_info)

    shared_drive_id = os.getenv("DRIVE_SHARED_DRIVE_ID")

    list_kwargs: dict[str, Any] = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "orderBy": "modifiedTime desc",
        "pageSize": limit,
        "fields": "files(id,name,webViewLink)",
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    if shared_drive_id:
        list_kwargs["corpora"] = "drive"
        list_kwargs["driveId"] = shared_drive_id

    response = service.files().list(**list_kwargs).execute()
    files = response.get("files", [])

    return [
        DriveFile(
            file_id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            web_view_link=item.get("webViewLink"),
        )
        for item in files
    ]

