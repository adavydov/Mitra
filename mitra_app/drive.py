import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveNotConfigured(RuntimeError):
    """Raised when Google Drive integration is not configured via environment variables."""


class DriveUploadError(RuntimeError):
    """Raised when Google Drive upload fails."""


def _load_service_account_info() -> dict[str, Any]:
    raw_json = os.getenv("DRIVE_SERVICE_ACCOUNT_JSON")
    raw_json_b64 = os.getenv("DRIVE_SERVICE_ACCOUNT_JSON_B64")

    if raw_json:
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise DriveUploadError("DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc

    if raw_json_b64:
        try:
            decoded = base64.b64decode(raw_json_b64).decode("utf-8")
            return json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DriveUploadError("DRIVE_SERVICE_ACCOUNT_JSON_B64 is not valid base64 JSON") from exc

    raise DriveNotConfigured(
        "Google Drive is not configured: set DRIVE_SERVICE_ACCOUNT_JSON or "
        "DRIVE_SERVICE_ACCOUNT_JSON_B64"
    )


def _build_drive_service(credentials_info: dict[str, Any]):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveUploadError(
            "Google Drive dependencies are not installed. "
            "Install google-api-python-client and google-auth."
        ) from exc

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=_DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def upload_markdown(title: str, markdown: str) -> dict[str, str | None]:
    """Upload markdown content to Google Drive and return identifiers/links."""
    root_folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not root_folder_id:
        raise DriveNotConfigured("Google Drive is not configured: set DRIVE_ROOT_FOLDER_ID")

    credentials_info = _load_service_account_info()
    drive_service = _build_drive_service(credentials_info)

    file_metadata = {
        "name": title,
        "parents": [root_folder_id],
        "mimeType": "text/markdown",
    }

    media_body = markdown.encode("utf-8")

    try:
        response = (
            drive_service.files()
            .create(
                body=file_metadata,
                media_body=media_body,
                fields="id,webViewLink",
            )
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive for external API errors
        logger.exception("Google Drive markdown upload failed")
        raise DriveUploadError("Google Drive markdown upload failed") from exc

    file_id = response.get("id")
    web_view_link = response.get("webViewLink")

    if not file_id:
        raise DriveUploadError("Google Drive response does not contain file id")

    logger.info("Uploaded markdown to Google Drive", extra={"file_id": file_id})
    return {"file_id": file_id, "webViewLink": web_view_link}
