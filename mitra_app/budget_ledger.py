from __future__ import annotations

import json
import logging
import os
from asyncio import Lock
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from googleapiclient.http import MediaInMemoryUpload

from mitra_app.drive import DriveNotConfigured, _build_drive_service, _load_service_account_info

logger = logging.getLogger(__name__)

_STATE_FOLDER_NAME = "mitra_state"
_STATE_FILE_NAME = "budget_ledger.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _default_limits() -> dict[str, int]:
    return {
        "tokens_in": int(os.getenv("BUDGET_LIMIT_TOKENS_IN", "200000")),
        "tokens_out": int(os.getenv("BUDGET_LIMIT_TOKENS_OUT", "200000")),
        "web_search_queries": int(os.getenv("BUDGET_LIMIT_WEB_SEARCH_QUERIES", "100")),
        "github_actions": int(os.getenv("BUDGET_LIMIT_GITHUB_ACTIONS", "20")),
    }


def _initial_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "day": _today_utc(),
        "limits": _default_limits(),
        "usage": {
            "tokens_in": 0,
            "tokens_out": 0,
            "web_search_queries": 0,
            "github_actions": 0,
        },
    }


class BudgetLedger:
    def __init__(self) -> None:
        self._state: dict[str, Any] = _initial_state()
        self._lock = Lock()
        self._state_file_id: str | None = None

    async def load(self) -> None:
        async with self._lock:
            try:
                payload = await self._read_from_drive()
            except DriveNotConfigured:
                logger.warning("budget_ledger_drive_not_configured")
                self._state = _initial_state()
                return
            except Exception:
                logger.exception("budget_ledger_load_failed")
                self._state = _initial_state()
                return

            if payload is None:
                self._state = _initial_state()
                await self._write_to_drive(self._state)
                return

            self._state = self._normalize(payload)

    async def record_llm_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        tokens_in, tokens_out = _extract_tokens(usage)
        if tokens_in == 0 and tokens_out == 0:
            return
        async with self._lock:
            self._reset_day_if_needed()
            self._state["usage"]["tokens_in"] += tokens_in
            self._state["usage"]["tokens_out"] += tokens_out
            await self._write_to_drive(self._state)

    async def record_web_search_query(self, count: int = 1) -> None:
        if count <= 0:
            return
        async with self._lock:
            self._reset_day_if_needed()
            self._state["usage"]["web_search_queries"] += count
            await self._write_to_drive(self._state)

    async def record_github_action(self, count: int = 1) -> None:
        if count <= 0:
            return
        async with self._lock:
            self._reset_day_if_needed()
            self._state["usage"]["github_actions"] += count
            await self._write_to_drive(self._state)

    async def reset_day(self) -> None:
        async with self._lock:
            self._state["day"] = _today_utc()
            self._state["usage"] = {
                "tokens_in": 0,
                "tokens_out": 0,
                "web_search_queries": 0,
                "github_actions": 0,
            }
            await self._write_to_drive(self._state)

    async def render_budget(self) -> str:
        async with self._lock:
            self._reset_day_if_needed()
            state = deepcopy(self._state)

        usage = state["usage"]
        limits = state["limits"]
        lines = [f"Budget day: {state['day']}"]
        for key in ("tokens_in", "tokens_out", "web_search_queries", "github_actions"):
            used = int(usage.get(key, 0))
            limit = int(limits.get(key, 0))
            remain = max(limit - used, 0)
            lines.append(f"- {key}: used={used}, limit={limit}, remain={remain}")
        return "\n".join(lines)

    def _reset_day_if_needed(self) -> None:
        if self._state.get("day") != _today_utc():
            self._state = _initial_state()

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = _initial_state()
        if not isinstance(payload, dict):
            return state

        state["day"] = str(payload.get("day") or state["day"])
        limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        for key in state["limits"]:
            try:
                state["limits"][key] = int(limits.get(key, state["limits"][key]))
            except (TypeError, ValueError):
                pass
            try:
                state["usage"][key] = int(usage.get(key, 0))
            except (TypeError, ValueError):
                state["usage"][key] = 0
        return state

    async def _read_from_drive(self) -> dict[str, Any] | None:
        root_folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
        if not root_folder_id:
            raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

        credentials_info = _load_service_account_info() if os.getenv("DRIVE_OAUTH_REFRESH_TOKEN") is None else {}
        service = _build_drive_service(credentials_info)

        folder_id = _find_file_id(service=service, name=_STATE_FOLDER_NAME, parent_id=root_folder_id, mime_type="application/vnd.google-apps.folder")
        if not folder_id:
            return None
        file_id = _find_file_id(service=service, name=_STATE_FILE_NAME, parent_id=folder_id)
        if not file_id:
            return None
        self._state_file_id = file_id

        raw = service.files().get_media(fileId=file_id).execute()
        if not raw:
            return None
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            return json.loads(raw)
        return None

    async def _write_to_drive(self, payload: dict[str, Any]) -> None:
        root_folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
        if not root_folder_id:
            raise DriveNotConfigured("Missing DRIVE_ROOT_FOLDER_ID")

        credentials_info = _load_service_account_info() if os.getenv("DRIVE_OAUTH_REFRESH_TOKEN") is None else {}
        service = _build_drive_service(credentials_info)

        folder_id = _find_file_id(service=service, name=_STATE_FOLDER_NAME, parent_id=root_folder_id, mime_type="application/vnd.google-apps.folder")
        if not folder_id:
            created = service.files().create(
                body={
                    "name": _STATE_FOLDER_NAME,
                    "parents": [root_folder_id],
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            folder_id = str(created.get("id", ""))

        body = json.dumps(payload, ensure_ascii=False, indent=2)
        media = MediaInMemoryUpload(body.encode("utf-8"), mimetype="application/json", resumable=False)

        file_id = self._state_file_id or _find_file_id(service=service, name=_STATE_FILE_NAME, parent_id=folder_id)
        if file_id:
            service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
            self._state_file_id = file_id
            return

        created = service.files().create(
            body={"name": _STATE_FILE_NAME, "parents": [folder_id], "mimeType": "application/json"},
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        self._state_file_id = str(created.get("id", ""))


def _find_file_id(service: Any, name: str, parent_id: str, mime_type: str | None = None) -> str | None:
    escaped_name = name.replace("'", "\\'")
    query = f"name = '{escaped_name}' and '{parent_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
    response = service.files().list(
        q=query,
        pageSize=1,
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = response.get("files", [])
    if not files:
        return None
    return str(files[0].get("id", ""))


def _extract_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    tokens_in = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    tokens_out = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        return int(tokens_in), int(tokens_out)
    except (TypeError, ValueError):
        return 0, 0


budget_ledger = BudgetLedger()

