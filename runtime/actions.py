from __future__ import annotations

from runtime.middleware import AuditMiddleware


def telegram_reply(
    middleware: AuditMiddleware,
    *,
    actor: str,
    request_id: str,
    chat_id: str,
    text: str,
) -> str:
    def _send() -> dict:
        # Здесь должен быть реальный вызов Telegram API.
        return {"status": "ok", "message_id": "msg-001"}

    _, execution_id = middleware.guarded_call(
        actor=actor,
        request_id=request_id,
        policy_ids=["C-OBS-01"],
        protocol_ids=["IR-LOG-02"],
        tool_name="telegram.reply",
        target=f"chat:{chat_id}",
        args={"chat_id": chat_id, "text": text},
        rollback_pointer=f"rollback://telegram/chat:{chat_id}",
        call=_send,
    )
    return f"{text}\n\n[evidence: {execution_id}]"


def drive_write(
    middleware: AuditMiddleware,
    *,
    actor: str,
    request_id: str,
    file_id: str,
    content: str,
) -> dict:
    def _write() -> dict:
        # Здесь должен быть реальный вызов Google Drive API.
        return {"status": "ok", "file_id": file_id, "bytes": len(content)}

    result, _ = middleware.guarded_call(
        actor=actor,
        request_id=request_id,
        policy_ids=["C-OBS-01"],
        protocol_ids=["IR-LOG-02"],
        tool_name="drive.write",
        target=f"file:{file_id}",
        args={"file_id": file_id, "size": len(content)},
        rollback_pointer=f"rollback://drive/file:{file_id}",
        call=_write,
    )
    return result
