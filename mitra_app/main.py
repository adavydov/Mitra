from __future__ import annotations

import json
from typing import Any

from mitra_app.audit.logger import log_event
from mitra_app.core.decision import format_result, format_status
from mitra_app.core.intake import classify
from mitra_app.core.policy_engine import enforce
from mitra_app.integrations.drive import DriveClient
from mitra_app.integrations.telegram import parse_update
from mitra_app.settings import load_settings


def _json(status: int, payload: dict[str, Any]) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    return status, headers, body


def handle_telegram_webhook(payload: dict, secret_header: str | None) -> tuple[int, dict[str, Any]]:
    settings = load_settings()
    if settings.telegram_webhook_secret and secret_header != settings.telegram_webhook_secret:
        return 401, {"detail": "invalid_secret"}

    user_id, text, _chat_id = parse_update(payload)
    cls = classify(text)
    decision = enforce(classification=cls, user_id=user_id, allowed_user_ids=settings.allowed_user_ids, autonomy_level=settings.autonomy_level)

    log_event({"event": "telegram_webhook", "user_id": user_id, "classification": cls, "decision": decision.reason, "message_text": text})

    if text.startswith("/status"):
        return 200, {
            "ok": True,
            "message": format_status(
                autonomy_level=settings.autonomy_level,
                risk=settings.risk_appetite,
                budget=settings.budget_daily_limit,
                capabilities=settings.capabilities,
            ),
        }

    if text.startswith("/report"):
        report_text = text.replace("/report", "", 1).strip() or "empty report request"
        drive = DriveClient(enabled=settings.drive_enabled, folder_id=settings.drive_folder)
        created, link_or_msg = drive.create_report(f"# Mitra report\n\n{report_text}\n")
        log_event({"event": "report_created", "created": created, "artifact": link_or_msg, "message_text": text})
        return 200, {"ok": True, "message": format_result(decision, f"Report processed: {link_or_msg}")}

    return 200, {"ok": decision.allow, "message": format_result(decision, "Command accepted")}


async def app(scope, receive, send):
    assert scope["type"] == "http"
    method = scope["method"]
    path = scope["path"]

    if method == "GET" and path == "/healthz":
        status, headers, body = _json(200, {"ok": True})
    elif method == "POST" and path == "/telegram/webhook":
        body_bytes = b""
        more_body = True
        while more_body:
            event = await receive()
            body_bytes += event.get("body", b"")
            more_body = event.get("more_body", False)
        try:
            payload = json.loads(body_bytes.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            status, headers, body = _json(400, {"detail": "invalid_json"})
        else:
            headers_in = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            status_code, resp = handle_telegram_webhook(payload, headers_in.get("x-telegram-bot-api-secret-token"))
            status, headers, body = _json(status_code, resp)
    else:
        status, headers, body = _json(404, {"detail": "not_found"})

    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
