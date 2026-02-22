from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from runtime.classification import classify_request
from runtime.policy_gate import apply_policy_gate
from runtime.redaction import redact_text


def _extract_message(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("message") or payload.get("edited_message") or {}


def process_telegram_update(payload: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    headers = headers or {}
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    incoming_secret = headers.get("X-Telegram-Bot-Api-Secret-Token", "")

    if expected_secret and incoming_secret != expected_secret:
        return 401, {"ok": False, "error": "unauthorized_webhook"}

    message = _extract_message(payload)
    raw_text = message.get("text") or message.get("caption") or ""
    classification = classify_request(raw_text)

    autonomy_level = os.getenv("AUTONOMY_LEVEL", "low")
    risk_appetite = os.getenv("RISK_APPETITE", "low")
    gate = apply_policy_gate(classification, autonomy_level, risk_appetite)

    response = {
        "ok": gate.decision == "allow",
        "request_id": f"tg:{payload.get('update_id', 'unknown')}",
        "source": "telegram",
        "classification": classification,
        "decision": gate.decision,
        "reason": gate.reason,
    }

    print(
        "telegram_intake",
        f"classification={classification}",
        f"decision={gate.decision}",
        f"text={redact_text(raw_text)}",
    )

    return (200 if gate.decision == "allow" else 403), response


class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhook/telegram":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        headers = {"X-Telegram-Bot-Api-Secret-Token": self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")}
        status, body = process_telegram_update(payload, headers=headers)
        self._send_json(status, body)


def run() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"server_started port={port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
