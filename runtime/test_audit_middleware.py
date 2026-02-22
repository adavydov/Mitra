import tempfile
import unittest

from runtime.actions import drive_write, telegram_reply
from runtime.audit import AuditWriter
from runtime.middleware import AuditMiddleware


class AuditMiddlewareTests(unittest.TestCase):
    def test_external_actions_write_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            writer = AuditWriter(path=f"{td}/events.ndjson")
            middleware = AuditMiddleware(writer=writer)

            reply = telegram_reply(
                middleware,
                actor="agent:mitra",
                request_id="req-1",
                chat_id="123",
                text="Принято",
            )
            self.assertIn("[evidence: ex-", reply)

            result = drive_write(
                middleware,
                actor="agent:mitra",
                request_id="req-2",
                file_id="file-007",
                content="hello",
            )
            self.assertEqual(result["status"], "ok")

            with open(f"{td}/events.ndjson", "r", encoding="utf-8") as f:
                lines = [line for line in f.readlines() if line.strip()]

            self.assertEqual(len(lines), 2)
            self.assertIn('"tool_call": {"name": "telegram.reply"', lines[0])
            self.assertIn('"tool_call": {"name": "drive.write"', lines[1])


if __name__ == "__main__":
    unittest.main()
