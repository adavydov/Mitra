from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
from typing import Any


@dataclass
class ToolCall:
    name: str
    target: str
    args_hash: str


@dataclass
class AuditEvent:
    timestamp: str
    actor: str
    request_id: str
    policy_ids: list[str]
    protocol_ids: list[str]
    tool_call: ToolCall
    outcome: str
    rollback_pointer: str | None
    execution_id: str
    evidence_uri: str


class AuditWriter:
    def __init__(self, path: str = "audit/events.ndjson") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["tool_call"] = asdict(event.tool_call)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_execution_id() -> str:
    return f"ex-{secrets.token_hex(3).upper()}"


def hash_args(args: dict[str, Any]) -> str:
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"
