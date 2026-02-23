from __future__ import annotations


def parse_update(payload: dict) -> tuple[int, str, int]:
    msg = payload.get("message") or payload.get("edited_message") or {}
    user_id = int((msg.get("from") or {}).get("id", 0))
    chat_id = int((msg.get("chat") or {}).get("id", 0))
    text = msg.get("text") or msg.get("caption") or ""
    return user_id, text, chat_id
