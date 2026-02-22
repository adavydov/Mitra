from __future__ import annotations

from typing import Callable

from runtime.audit import AuditEvent, AuditWriter, ToolCall, hash_args, now_utc, short_execution_id


class AuditMiddleware:
    """Fail-closed middleware: external tool call is blocked if audit write fails."""

    def __init__(self, writer: AuditWriter | None = None) -> None:
        self.writer = writer or AuditWriter()

    def guarded_call(
        self,
        *,
        actor: str,
        request_id: str,
        policy_ids: list[str],
        protocol_ids: list[str],
        tool_name: str,
        target: str,
        args: dict,
        rollback_pointer: str | None,
        call: Callable[[], dict],
    ) -> tuple[dict, str]:
        execution_id = short_execution_id()
        event = AuditEvent(
            timestamp=now_utc(),
            actor=actor,
            request_id=request_id,
            policy_ids=policy_ids,
            protocol_ids=protocol_ids,
            tool_call=ToolCall(name=tool_name, target=target, args_hash=hash_args(args)),
            outcome="allowed",
            rollback_pointer=rollback_pointer,
            execution_id=execution_id,
            evidence_uri=f"audit://events/{request_id}/{execution_id}",
        )
        self.writer.write(event)
        result = call()
        return result, execution_id
