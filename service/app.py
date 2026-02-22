"""Minimal webhook listener for Render Web Service."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from evidence import record
from orchestrator import execute
from policy import evaluate


class MitraHandler(BaseHTTPRequestHandler):
    server_version = "MitraWebhook/1.0"

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhook":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)

        try:
            event = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return

        decision = evaluate(event, os.getenv("SERVICE_SHARED_SECRET"))
        if not decision.allowed:
            record(event, "rejected", decision.reason)
            self._send_json(HTTPStatus.FORBIDDEN, {"status": "rejected", "reason": decision.reason})
            return

        result = execute(event)
        record(event, "processed", result["result"])
        self._send_json(HTTPStatus.ACCEPTED, {"status": "accepted", "task": result})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), MitraHandler)
    print(f"Mitra webhook service listening on :{port}")
    server.serve_forever()
