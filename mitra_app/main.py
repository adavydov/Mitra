import json
import logging
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import time
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException
from googleapiclient.errors import HttpError

import mitra_app.audit as audit
from mitra_app.audit import log_report_event
from mitra_app.budget_ledger import budget_ledger
from mitra_app.policy_enforcer import CommandPolicy, CommandPolicyEnforcer, EnforcementDecision
from mitra_app.drive import (
    DriveNotConfigured,
    OAuthRefreshInvalidGrant,
    delete_file,
    get_drive_auth_mode,
    get_last_oauth_refresh_time,
    list_recent_files,
    trash_file,
    upload_markdown,
)
from mitra_app.llm.anthropic import AnthropicClient
from mitra_app.research import ResearchError, build_research_reply, run_research
from mitra_app.telegram import ensure_webhook, send_message
from mitra_app.search import SearchRateLimitExceeded, brave_web_search, format_search_results
from mitra_app import github

app = FastAPI()
logger = logging.getLogger(__name__)

_THINK_PROMPT_MAX_CHARS = 1200
_THINK_OUTPUT_MAX_CHARS = 900
_SECRET_ENV_NAME_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PRIVATE|API_KEY|ACCESS_KEY|CLIENT_SECRET)", re.IGNORECASE)
_THINK_SYSTEM_PROMPT = (
    "Ты помощник в режиме /think. Нужен только анализ текста пользователя без внешних действий. "
    "Не используйте веб, GitHub, Drive, интеграции, инструменты или вызовы функций. "
    "Верни ответ в формате:\n"
    "Короткий ответ: ...\n"
    "Допущения: ...\n"
    "Следующие шаги: ..."
)

HELP_TEXT = (
    "Commands: /status, /oauth_status, /search <query>, /research <query>, /think <prompt>, "
    "/report <text>, /pr <title>\\n<spec>, /pr_status <issue#|pr#>, /drive_check, /budget, "
    "/smoke, /smoke_deep"
)


def _sensitive_env_names() -> set[str]:
    defaults = {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "DRIVE_OAUTH_CLIENT_SECRET",
        "DRIVE_OAUTH_REFRESH_TOKEN",
        "DRIVE_SERVICE_ACCOUNT_JSON",
        "DRIVE_SERVICE_ACCOUNT_JSON_B64",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
    }
    for key in os.environ:
        if _SECRET_ENV_NAME_RE.search(key):
            defaults.add(key)
    return defaults


def _sanitize_think_prompt(prompt: str) -> str:
    sanitized = prompt.strip()

    for env_name in _sensitive_env_names():
        escaped_name = re.escape(env_name)
        sanitized = re.sub(rf"(?i){escaped_name}\s*[:=]\s*[^\s,;]+", f"{env_name}=[REDACTED]", sanitized)
        sanitized = re.sub(rf"(?i)\b{escaped_name}\b", f"{env_name}", sanitized)

        secret_value = os.getenv(env_name)
        if secret_value:
            sanitized = sanitized.replace(secret_value, "[REDACTED]")

    return sanitized


def _trim_prompt(prompt: str, limit: int = _THINK_PROMPT_MAX_CHARS) -> str:
    trimmed = prompt[:limit].strip()
    if len(prompt) <= limit:
        return trimmed
    return f"{trimmed}…"


def _build_think_reply(question: str) -> str:
    sanitized = _trim_prompt(_sanitize_think_prompt(question))
    if not sanitized:
        return "Usage: /think <вопрос/задача>"

    llm_reply = _invoke_think_llm(sanitized)
    if not llm_reply:
        return "Не удалось получить ответ LLM для /think"

    return _cap_output_chars(llm_reply, _THINK_OUTPUT_MAX_CHARS)


def _invoke_think_llm(prompt: str, llm_client: AnthropicClient | None = None) -> str:
    client = llm_client or AnthropicClient()
    response = client.create_message(
        messages=[{"role": "user", "content": prompt}],
        system=_THINK_SYSTEM_PROMPT,
    )
    content = response.get("content")
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

    return "\n".join(parts).strip()


def _cap_output_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def _extract_think_prompt(text: str) -> str:
    command, _, remainder = text.partition(" ")
    if command.startswith("/think"):
        return remainder.strip()
    return ""


def _audit_think_command(action_id: str, user_id: int | None, command: str, outcome: str) -> None:
    _safe_audit_event(
        {
            "event": "telegram_think",
            "action_id": action_id,
            "user_id": user_id,
            "command": command,
            "outcome": outcome,
            "log_level": "info" if outcome in {"success", "usage"} else "error",
        }
    )


def _extract_think_prompt(text: str) -> str:
    return text[len("/think") :].strip()[:240]


def _sanitize_drive_http_error(exc: HttpError) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(exc, "resp", None), "status", "unknown")

    reason: str | None = None
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        try:
            payload = json.loads(content.decode("utf-8"))
            reason = (((payload.get("error") or {}).get("errors") or [{}])[0]).get("reason")
        except (UnicodeDecodeError, json.JSONDecodeError, IndexError, AttributeError, TypeError):
            reason = None

    if not reason:
        get_reason = getattr(exc, "_get_reason", None)
        if callable(get_reason):
            reason = str(get_reason())

    if not reason:
        reason = str(getattr(getattr(exc, "resp", None), "reason", "unknown"))

    return f"Drive error: {status_code} {reason}"

_COMMAND_POLICIES: dict[str, CommandPolicy] = {
    "/status": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/oauth_status": CommandPolicy(required_al="AL1", risk_level="R1", budget_category="search"),
    "/whoami": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/help": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/start": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/smoke": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/smoke_deep": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="search"),
    "/reports": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/report": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/pr_status": CommandPolicy(required_al="AL1", risk_level="R1", budget_category="search"),
    "/drive_check": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/budget": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
}

_policy_enforcer = CommandPolicyEnforcer(Path(__file__).resolve().parents[1])


def _current_autonomy_level() -> str:
    return os.getenv("MITRA_AUTONOMY_LEVEL", "AL2")


def _audit_policy_denied(
    *,
    user_id: int | None,
    chat_id: int | None,
    action_id: str,
    telegram_update_id: int | None,
    action_type: str,
    required_al: str,
    current_al: str,
    risk_level: str,
    budget_category: str,
    reason: str,
) -> None:
    _safe_audit_event(
        {
            "event": "telegram_policy_denied",
            "action_id": action_id,
            "telegram_update_id": telegram_update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "action_type": action_type,
            "required_al": required_al,
            "current_al": current_al,
            "risk_level": risk_level,
            "budget_category": budget_category,
            "outcome": "denied",
            "reason": reason,
            "log_level": "info",
        }
    )


def _enforce_command_policy(
    *,
    action_type: str,
    action_id: str,
    telegram_update_id: int | None,
    user_id: int | None,
    chat_id: int | None,
) -> str | None:
    policy = _COMMAND_POLICIES.get(action_type)
    if policy is None:
        return None

    current_al = _current_autonomy_level()
    try:
        decision = _policy_enforcer.enforce(current_al=current_al, policy=policy)
    except Exception:
        logger.exception("policy_enforcement_failed", extra={"action_type": action_type})
        decision = EnforcementDecision(
            allowed=False,
            reason=f"Denied: requires {policy.required_al}/{policy.risk_level}",
        )
    if decision.allowed:
        return None

    _audit_policy_denied(
        user_id=user_id,
        chat_id=chat_id,
        action_id=action_id,
        telegram_update_id=telegram_update_id,
        action_type=action_type,
        required_al=policy.required_al,
        current_al=current_al,
        risk_level=policy.risk_level,
        budget_category=policy.budget_category,
        reason=decision.reason or "Denied",
    )

    return decision.reason or "Denied"



@app.on_event("startup")
async def startup_sync_webhook() -> None:
    try:
        if budget_ledger:
            await budget_ledger.load()
    except Exception:
        logger.exception("startup_budget_ledger_failed")

    try:
        logger.info(
            "drive_auth_state",
            extra={"mode": get_drive_auth_mode(), "last_refresh_at": get_last_oauth_refresh_time()},
        )
        ok, detail = await ensure_webhook()
        if not ok:
            logger.warning("startup_webhook_sync_failed", extra={"detail": detail})
    except Exception:
        logger.exception("startup_webhook_sync_failed")


class RecentUpdateDeduplicator:
    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._seen_update_ids: OrderedDict[int, None] = OrderedDict()
        self._lock = Lock()

    def is_duplicate(self, update_id: int) -> bool:
        with self._lock:
            if update_id in self._seen_update_ids:
                self._seen_update_ids.move_to_end(update_id)
                return True

            self._seen_update_ids[update_id] = None
            if len(self._seen_update_ids) > self._max_size:
                self._seen_update_ids.popitem(last=False)
            return False


_recent_update_deduplicator = RecentUpdateDeduplicator(max_size=1000)


class PerUserRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._events_by_user: dict[int, list[float]] = {}
        self._lock = Lock()

    def allow(self, user_id: int | None) -> bool:
        if user_id is None:
            return False

        now_ts = datetime.now(timezone.utc).timestamp()
        min_ts = now_ts - self._window_seconds

        with self._lock:
            history = self._events_by_user.setdefault(user_id, [])
            history[:] = [event_ts for event_ts in history if event_ts >= min_ts]
            if len(history) >= self._limit:
                return False
            history.append(now_ts)
            return True


_pr_rate_limiter = PerUserRateLimiter(limit=5, window_seconds=3600)


def _parse_pr_command(text: str) -> tuple[str, str] | None:
    body = text[len("/pr") :].lstrip()
    if not body:
        return None

    if "\n" in body:
        title, spec = body.split("\n", 1)
    else:
        title, spec = body, ""

    title = title.strip()
    spec = spec.strip()

    if not title:
        return None

    return title, spec


async def _create_github_issue(title: str, body: str) -> tuple[int, str]:
    issue = await github.create_issue(title=title, body=body, labels=["mitra:codex"])
    issue_number = issue.number
    issue_url = issue.html_url
    if issue_number <= 0 or not issue_url:
        raise RuntimeError("GitHub issue create returned invalid response")

    return issue_number, issue_url




def _parse_pr_status_command(text: str) -> str | None:
    body = text[len("/pr_status") :].strip()
    return body or None


def _parse_pr_or_issue_ref(ref: str) -> tuple[str, int] | None:
    normalized = ref.strip()
    if not normalized:
        return None

    lower = normalized.lower()
    kind = "issue"
    if "pull/" in lower or "pulls/" in lower or lower.startswith("pr"):
        kind = "pr"

    match = re.search(r"(\d+)\s*$", normalized)
    if not match:
        return None

    number = int(match.group(1))
    if number <= 0:
        return None

    return kind, number


async def _build_pr_status_reply(ref: str) -> str:
    parsed_ref = _parse_pr_or_issue_ref(ref)
    if parsed_ref is None:
        return "Usage: /pr_status <issue#|pr#>"

    ref_kind, ref_number = parsed_ref

    try:
        if ref_kind == "pr":
            pr_number = ref_number
            pr_status = await github.get_pr_status(pr_number)
            pr_url = pr_status.html_url
        else:
            issue_number = ref_number
            linked_pr = await github.find_linked_pr(issue_number)
            if linked_pr is None:
                return f"No linked PR found for issue #{issue_number}"
            pr_number = linked_pr.number
            pr_url = linked_pr.html_url

        pr_status = await github.get_pr_status(pr_number)
        checks = await github.get_pr_checks_summary(pr_status.head_sha)
    except Exception:
        logger.exception("telegram_pr_status_failed", extra={"reference": ref})
        return "Failed to fetch PR status"

    state = pr_status.state or "unknown"
    if pr_status.draft:
        state = f"{state}, draft"
    if pr_status.merged:
        state = "merged"

    return (
        f"PR: {pr_url}\n"
        f"State: {state}\n"
        f"Checks: total={checks.total}, success={checks.successful}, failed={checks.failed}, pending={checks.pending}"
    )


def _load_allowed_user_ids() -> set[int]:
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
    allowed: set[int] = set()

    for value in raw.split(","):
        stripped = value.strip()
        if not stripped:
            continue
        try:
            allowed.add(int(stripped))
        except ValueError:
            logger.warning("Ignoring invalid ALLOWED_TELEGRAM_USER_IDS value", extra={"value": stripped})

    return allowed


def _is_allowlist_configured(raw_value: str | None) -> bool:
    return bool(raw_value and raw_value.strip())


def _audit_allowlist_denied(
    user_id: int | None,
    chat_id: int | None,
    action_id: str,
    telegram_update_id: int | None,
    action_type: str,
) -> None:
    _safe_audit_event(
        {
            "event": "telegram_allowlist_denied",
            "action_id": action_id,
            "telegram_update_id": telegram_update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "action_type": action_type,
            "outcome": "denied",
            "log_level": "info",
        }
    )


def _audit_dedup(update_id: int, user_id: int | None, chat_id: int | None, action_id: str) -> None:
    event = {
        "event": "telegram_dedup",
        "action_id": action_id,
        "telegram_update_id": update_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "action_type": "dedup_check",
        "outcome": "dedup",
        "log_level": "info",
    }

    _safe_audit_event(event)


def _safe_audit_event(event: dict[str, object]) -> None:
    log_event = getattr(audit, "log_event", None)
    if callable(log_event):
        try:
            log_event(event)
        except Exception:
            logger.exception("telegram_audit_failed", extra={"event": event})
        return

    logger.info("telegram_audit_event", extra=event)




def _audit_research_failure(
    *,
    action_id: str,
    telegram_update_id: int | None,
    user_id: int | None,
    chat_id: int | None,
    reason: str,
) -> None:
    _safe_audit_event(
        {
            "event": "telegram_research_failed",
            "action_id": action_id,
            "telegram_update_id": telegram_update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "action_type": "/research",
            "outcome": "error",
            "reason": reason,
            "log_level": "error",
        }
    )

def _build_report_title(now: datetime) -> str:
    return f"mitra-report {now.strftime('%Y-%m-%d %H:%M')}"


def _build_report_body(text: str, now: datetime, user_id: int | None) -> str:
    timestamp = now.isoformat()
    return "\n".join(
        [
            text.strip(),
            "",
            "---",
            f"timestamp: {timestamp}",
            f"user_id: {user_id}",
        ]
    )


def _sanitize_report_error(exc: Exception) -> str:
    if isinstance(exc, DriveNotConfigured):
        return "Drive disabled"

    if isinstance(exc, HttpError):
        status = str(exc.status_code)
        reason = "unknown"

        if exc.content:
            try:
                payload = json.loads(exc.content.decode("utf-8"))
                error_obj = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error_obj, dict):
                    errors = error_obj.get("errors")
                    if isinstance(errors, list) and errors:
                        first_error = errors[0]
                        if isinstance(first_error, dict) and first_error.get("reason"):
                            reason = str(first_error["reason"])
                    elif error_obj.get("status"):
                        reason = str(error_obj["status"])
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                reason = "unknown"

        return f"Drive error: {status} {reason}"

    return "Report failed"


def _sanitize_research_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else "unknown"
        return f"Research failed ({status})"

    if isinstance(exc, httpx.HTTPError):
        return "Research failed (network error)"

    return "Research failed"


def _audit_drive_check(user_id: int | None, chat_id: int | None, auth_mode: str, outcome: str, detail: str) -> None:
    event = {
        "event": "drive_check",
        "user_id": user_id,
        "chat_id": chat_id,
        "auth_mode": auth_mode,
        "outcome": outcome,
        "detail": detail,
    }

    log_event = getattr(audit, "log_event", None)
    if callable(log_event):
        log_event(event)
        return

    logger.info("drive_check", extra=event)


def _safe_drive_check_error(exc: Exception) -> str:
    if isinstance(exc, DriveNotConfigured):
        return "Drive error: drive_not_configured"

    if isinstance(exc, HttpError):
        return _sanitize_drive_http_error(exc)

    return "Drive error: unknown drive_check_failed"


async def _run_drive_check(auth_mode: str) -> tuple[str, str]:
    started_at = perf_counter()
    check_body = "# mitra drive check\n\nhealth ping"
    upload = await upload_markdown(title="mitra-drive-check", markdown_body=check_body)
    file_id = upload.file_id or "unknown"
    await trash_file(file_id)
    latency_ms = int((perf_counter() - started_at) * 1000)
    reply = f"Drive OK (auth={auth_mode}) latency_ms={latency_ms} file_id={file_id} (deleted)"
    return reply, "upload+trash ok"


def _is_budget_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    owner_id = os.getenv("MITRA_ADMIN_TELEGRAM_USER_ID")
    if owner_id is None:
        return False
    return str(user_id) == owner_id.strip()


def _smoke_line(name: str, status: str, reason: str) -> str:
    return f"- {name}: {status} ({reason})"


def _is_drive_configured() -> bool:
    if not os.getenv("DRIVE_ROOT_FOLDER_ID"):
        return False
    if get_drive_auth_mode() == "oauth":
        return bool(os.getenv("DRIVE_OAUTH_CLIENT_ID") and os.getenv("DRIVE_OAUTH_CLIENT_SECRET") and os.getenv("DRIVE_OAUTH_REFRESH_TOKEN"))
    return bool(os.getenv("DRIVE_SERVICE_ACCOUNT_JSON") or os.getenv("DRIVE_SERVICE_ACCOUNT_JSON_B64"))


def _is_budget_ledger_loaded() -> bool | None:
    if budget_ledger is None:
        return None
    state = getattr(budget_ledger, "_state", None)
    return isinstance(state, dict) and bool(state)


def _build_smoke_reply(*, user_id: int | None, allowlist_configured: bool, allowed_user_ids: set[int]) -> str:
    lines = [
        _smoke_line("telegram", "OK", "webhook command processed"),
    ]

    if not allowlist_configured:
        lines.append(_smoke_line("allowlist", "FAIL", "ALLOWED_TELEGRAM_USER_IDS missing"))
    elif user_id in allowed_user_ids:
        lines.append(_smoke_line("allowlist", "OK", f"user_id={user_id} allowed"))
    else:
        lines.append(_smoke_line("allowlist", "FAIL", f"user_id={user_id} not in allowlist"))

    auth_mode = get_drive_auth_mode()
    last_refresh_at = get_last_oauth_refresh_time() or "never"
    lines.append(_smoke_line("oauth", "OK", f"auth_mode={auth_mode}, last_refresh_at={last_refresh_at}"))

    lines.append(_smoke_line("drive", "OK" if _is_drive_configured() else "FAIL", "configured" if _is_drive_configured() else "env missing"))

    ledger_loaded = _is_budget_ledger_loaded()
    if ledger_loaded is None:
        lines.append(_smoke_line("budgets", "NA", "ledger disabled"))
    elif ledger_loaded:
        lines.append(_smoke_line("budgets", "OK", "ledger loaded"))
    else:
        lines.append(_smoke_line("budgets", "FAIL", "ledger not loaded"))

    lines.append(_smoke_line("llm", "OK" if os.getenv("ANTHROPIC_API_KEY") else "FAIL", "configured" if os.getenv("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY missing"))
    lines.append(_smoke_line("search", "OK" if os.getenv("BRAVE_SEARCH_API_KEY") else "FAIL", "configured" if os.getenv("BRAVE_SEARCH_API_KEY") else "BRAVE_SEARCH_API_KEY missing"))
    return "\n".join(lines)


async def _run_smoke_deep_checks() -> tuple[str, dict[str, object]]:
    lines: list[str] = []
    audit_payload: dict[str, object] = {"event": "smoke_deep"}

    drive_start = time.perf_counter()
    try:
        upload = await upload_markdown(title="mitra-smoke-deep", markdown_body="ok")
        await delete_file(upload.file_id)
        drive_latency_ms = int((time.perf_counter() - drive_start) * 1000)
        lines.append(_smoke_line("drive_deep", "OK", f"latency_ms={drive_latency_ms}"))
        audit_payload["drive"] = {"status": "ok", "latency_ms": drive_latency_ms}
    except Exception as exc:
        drive_latency_ms = int((time.perf_counter() - drive_start) * 1000)
        detail = _sanitize_report_error(exc)
        lines.append(_smoke_line("drive_deep", "FAIL", f"{detail}, latency_ms={drive_latency_ms}"))
        audit_payload["drive"] = {"status": "fail", "detail": detail, "latency_ms": drive_latency_ms}

    llm_start = time.perf_counter()
    try:
        llm_payload = AnthropicClient(max_tokens_out=8).create_message([{"role": "user", "content": "Reply with PONG"}])
        response_text = json.dumps(llm_payload).upper()
        llm_latency_ms = int((time.perf_counter() - llm_start) * 1000)
        if "PONG" in response_text:
            lines.append(_smoke_line("llm_deep", "OK", f"latency_ms={llm_latency_ms}"))
            audit_payload["llm"] = {"status": "ok", "latency_ms": llm_latency_ms}
        else:
            lines.append(_smoke_line("llm_deep", "FAIL", f"unexpected_response, latency_ms={llm_latency_ms}"))
            audit_payload["llm"] = {"status": "fail", "detail": "unexpected_response", "latency_ms": llm_latency_ms}
    except Exception:
        llm_latency_ms = int((time.perf_counter() - llm_start) * 1000)
        lines.append(_smoke_line("llm_deep", "FAIL", f"request_failed, latency_ms={llm_latency_ms}"))
        audit_payload["llm"] = {"status": "fail", "detail": "request_failed", "latency_ms": llm_latency_ms}

    if not os.getenv("BRAVE_SEARCH_API_KEY"):
        lines.append(_smoke_line("search_deep", "NA", "BRAVE_SEARCH_API_KEY missing"))
        audit_payload["search"] = {"status": "na", "detail": "api_key_missing"}
    else:
        search_start = time.perf_counter()
        try:
            await brave_web_search("mitra smoke ping")
            search_latency_ms = int((time.perf_counter() - search_start) * 1000)
            lines.append(_smoke_line("search_deep", "OK", f"latency_ms={search_latency_ms}"))
            audit_payload["search"] = {"status": "ok", "latency_ms": search_latency_ms}
        except Exception:
            search_latency_ms = int((time.perf_counter() - search_start) * 1000)
            lines.append(_smoke_line("search_deep", "FAIL", f"request_failed, latency_ms={search_latency_ms}"))
            audit_payload["search"] = {"status": "fail", "detail": "request_failed", "latency_ms": search_latency_ms}

    return "\n".join(lines), audit_payload


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/drive_check")
async def drive_check() -> dict[str, str]:
    auth_mode = get_drive_auth_mode()
    try:
        status, _ = await _run_drive_check(auth_mode)
    except Exception as exc:
        status = _safe_drive_check_error(exc)
    payload = {"auth_mode": auth_mode, "status": status}
    return payload


@app.post("/telegram/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret or x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        message = update.get("message") or {}
        update_id = update.get("update_id")
        action_id = f"act-{uuid4().hex[:12]}"
        telegram_update_id = update_id if isinstance(update_id, int) else None
        text = message.get("text", "")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        from_user = message.get("from") or {}
        user_id = from_user.get("id")
        action_type = text.split()[0] if isinstance(text, str) and text else "no_command"

        if isinstance(update_id, int) and _recent_update_deduplicator.is_duplicate(update_id):
            _audit_dedup(update_id=update_id, user_id=user_id, chat_id=chat_id, action_id=action_id)
            return {"status": "ok"}

        allowed_user_ids_raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS")
        allowed_user_ids = _load_allowed_user_ids()
        allowlist_configured = _is_allowlist_configured(allowed_user_ids_raw)

        if allowlist_configured and user_id not in allowed_user_ids:
            _audit_allowlist_denied(
                user_id=user_id,
                chat_id=chat_id,
                action_id=action_id,
                telegram_update_id=telegram_update_id,
                action_type=action_type,
            )
            return {"status": "ok"}

        policy_bypass_commands = {"/status", "/oauth_status", "/whoami", "/help", "/start", "/smoke"}
        if allowlist_configured or action_type in policy_bypass_commands:
            deny_reason = _enforce_command_policy(
                action_type=action_type,
                action_id=action_id,
                telegram_update_id=telegram_update_id,
                user_id=user_id,
                chat_id=chat_id,
            )
            if deny_reason is not None:
                if chat_id is not None:
                    await send_message(chat_id=chat_id, text=deny_reason)
                return {"status": "ok"}

        if text.startswith("/status"):
            reply_text = "Mitra alive"
        elif text.startswith("/smoke_deep"):
            reply_text, smoke_audit = await _run_smoke_deep_checks()
            _safe_audit_event(
                {
                    "event": "telegram_smoke_deep",
                    "action_id": action_id,
                    "telegram_update_id": telegram_update_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "action_type": "/smoke_deep",
                    "outcome": "completed",
                    "checks": smoke_audit,
                    "log_level": "info",
                }
            )
        elif text.startswith("/smoke"):
            reply_text = _build_smoke_reply(
                user_id=user_id if isinstance(user_id, int) else None,
                allowlist_configured=allowlist_configured,
                allowed_user_ids=allowed_user_ids,
            )
            _safe_audit_event(
                {
                    "event": "telegram_smoke",
                    "action_id": action_id,
                    "telegram_update_id": telegram_update_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "action_type": "/smoke",
                    "outcome": "completed",
                    "log_level": "info",
                }
            )
        elif text.startswith("/oauth_status"):
            auth_mode = get_drive_auth_mode()
            last_refresh_at = get_last_oauth_refresh_time() or "never"
            logger.info("oauth_status_requested", extra={"mode": auth_mode, "last_refresh_at": last_refresh_at})
            reply_text = f"auth_mode={auth_mode}, last_refresh_at={last_refresh_at}"
        elif text.startswith("/whoami"):
            reply_text = f"user_id={user_id}, chat_id={chat_id}"
        elif text.startswith("/search"):
            query = text[len("/search") :].strip()
            if not query:
                reply_text = "Usage: /search <query>"
            elif not os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
                reply_text = "Search not configured"
            else:
                try:
                    search_results = await brave_web_search(query)
                    reply_text = format_search_results(search_results)
                    audit.log_budget_usage(
                        category="search_queries",
                        amount=1,
                        metadata={"user_id": user_id, "chat_id": chat_id, "query": query},
                    )
                except SearchRateLimitExceeded as exc:
                    reply_text = str(exc)
                except Exception:
                    reply_text = "Search failed"
                    logger.exception("search_command_failed")
        elif text.startswith("/llm_check"):
            try:
                reply_text = await _run_llm_check()
                _safe_audit_event(
                    {
                        "event": "llm_check",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/llm_check",
                        "outcome": "ok" if reply_text.startswith("LLM OK") else "not_configured",
                        "detail": reply_text,
                        "log_level": "info",
                    }
                )
            except Exception as exc:
                logger.exception("llm_check_failed")
                reply_text = _sanitize_llm_error(exc)
                _safe_audit_event(
                    {
                        "event": "llm_check",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/llm_check",
                        "outcome": "error",
                        "detail": repr(exc),
                        "log_level": "error",
                    }
                )
        elif not allowlist_configured:
            reply_text = "Allowlist not configured. Set ALLOWED_TELEGRAM_USER_IDS."
        elif text.startswith("/think"):
            think_prompt = _extract_think_prompt(text)
            if not think_prompt:
                reply_text = "Usage: /think <вопрос/задача>"
                _audit_think_command(action_id=action_id, user_id=user_id, command="/think", outcome="usage")
            else:
                try:
                    reply_text = _build_think_reply(think_prompt)
                    _audit_think_command(action_id=action_id, user_id=user_id, command="/think", outcome="success")
                except Exception:
                    logger.exception("think_command_failed")
                    reply_text = "Не удалось получить ответ LLM для /think"
                    _audit_think_command(action_id=action_id, user_id=user_id, command="/think", outcome="error")
        elif text.startswith("/reports"):
            try:
                files = await list_recent_files(limit=5)
                if not files:
                    reply_text = "No reports found"
                else:
                    lines = ["Latest reports:"]
                    for drive_file in files:
                        link = drive_file.web_view_link or drive_file.file_id
                        lines.append(f"- {drive_file.name}: {link}")
                    reply_text = "\n".join(lines)
            except Exception as exc:
                reply_text = _sanitize_report_error(exc)
                logger.exception("report_list_failed")
        elif text.startswith("/research"):
            query = text[len("/research") :].strip()
            if not query:
                reply_text = "Usage: /research <query>"
            else:
                try:
                    items, summary = await run_research(query)
                    reply_text = build_research_reply(query, items, summary)
                except ResearchError as exc:
                    reply_text = str(exc)
                    _audit_research_failure(
                        action_id=action_id,
                        telegram_update_id=telegram_update_id,
                        user_id=user_id,
                        chat_id=chat_id,
                        reason="research_error",
                    )
                except Exception as exc:
                    reply_text = f"Research failed: {str(exc).replace(chr(10), ' ').strip()}"
                    logger.exception("research_command_failed")
                    _audit_research_failure(
                        action_id=action_id,
                        telegram_update_id=telegram_update_id,
                        user_id=user_id,
                        chat_id=chat_id,
                        reason="unexpected_error",
                    )
        elif text.startswith("/report"):
            report_text = text[len("/report") :].strip()
            file_id = ""

            if not report_text:
                reply_text = "Usage: /report <text>"
                log_report_event(
                    action_id=action_id,
                    telegram_update_id=telegram_update_id,
                    file_id=file_id,
                    outcome="invalid",
                    user_id=user_id,
                    chat_id=chat_id,
                    action_type="/report",
                    log_level="info",
                )
            else:
                now = datetime.now(timezone.utc)
                title = _build_report_title(now)
                body = _build_report_body(report_text, now, user_id=user_id)

                try:
                    upload = await upload_markdown(title=title, markdown_body=body)
                    file_id = upload.file_id
                    link = upload.web_view_link or upload.file_id
                    reply_text = f"Saved: {link}"
                    await budget_ledger.record_drive_write()
                    log_report_event(
                        action_id=action_id,
                        telegram_update_id=telegram_update_id,
                        file_id=file_id,
                        outcome="success",
                        user_id=user_id,
                        chat_id=chat_id,
                        link=link,
                        action_type="/report",
                        log_level="info",
                    )
                except DriveNotConfigured as exc:
                    reply_text = _sanitize_report_error(exc)
                    logger.exception("report_upload_drive_not_configured")
                    log_report_event(
                        action_id=action_id,
                        telegram_update_id=telegram_update_id,
                        file_id=file_id,
                        outcome="drive_disabled",
                        user_id=user_id,
                        chat_id=chat_id,
                        action_type="/report",
                        log_level="error",
                    )
                except OAuthRefreshInvalidGrant as exc:
                    reply_text = str(exc)
                    logger.warning(
                        "report_upload_oauth_expired",
                        extra={"mode": get_drive_auth_mode(), "last_refresh_at": get_last_oauth_refresh_time()},
                    )
                    log_report_event(
                        action_id=action_id,
                        file_id=file_id,
                        outcome="oauth_expired",
                        user_id=user_id,
                        chat_id=chat_id,
                        action_type="/report",
                        log_level="warning",
                    )
                except Exception as exc:
                    reply_text = _sanitize_report_error(exc)
                    logger.exception("report_upload_failed")
                    log_report_event(
                        action_id=action_id,
                        telegram_update_id=telegram_update_id,
                        file_id=file_id,
                        outcome="error",
                        user_id=user_id,
                        chat_id=chat_id,
                        action_type="/report",
                        log_level="error",
                    )
        elif text.startswith("/pr_status"):
            ref = _parse_pr_status_command(text)
            if ref is None:
                reply_text = "Usage: /pr_status <issue#|pr#>"
            else:
                reply_text = await _build_pr_status_reply(ref)
        elif text.startswith("/pr"):
            parsed = _parse_pr_command(text)
            if not parsed:
                reply_text = "Usage: /pr <title>\\n<spec>"
            elif not _pr_rate_limiter.allow(user_id if isinstance(user_id, int) else None):
                reply_text = "Rate limit exceeded: max 5 /pr per hour"
                _safe_audit_event(
                    {
                        "event": "telegram_pr_open_issue",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/pr",
                        "issue_number": None,
                        "outcome": "rate_limited",
                        "log_level": "info",
                    }
                )
            else:
                title, spec = parsed
                issue_body = spec or "(no spec provided)"
                issue_number: int | None = None

                try:
                    issue_number, issue_url = await _create_github_issue(title=title, body=issue_body)
                    await budget_ledger.record_github_write()
                    reply_text = f"Created: {issue_url}"
                    outcome = "success"
                except Exception:
                    logger.exception("telegram_pr_create_issue_failed")
                    reply_text = "Failed to create issue"
                    outcome = "error"

                _safe_audit_event(
                    {
                        "event": "telegram_pr_open_issue",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/pr",
                        "issue_number": issue_number,
                        "outcome": outcome,
                        "log_level": "info" if outcome in {"success", "usage"} else "error",
                    }
                )
        elif text.startswith("/drive_check"):
            auth_mode = get_drive_auth_mode()

            try:
                reply_text, detail = await _run_drive_check(auth_mode)
                _audit_drive_check(user_id=user_id, chat_id=chat_id, auth_mode=auth_mode, outcome="success", detail=detail)
            except Exception as exc:
                detail = _safe_drive_check_error(exc)
                reply_text = detail
                logger.exception("drive_check_command_failed")
                _audit_drive_check(user_id=user_id, chat_id=chat_id, auth_mode=auth_mode, outcome="error", detail=detail)
        elif text.startswith("/budget_reset_day"):
            if _is_budget_admin(user_id):
                await budget_ledger.reset_day()
                reply_text = "Budget day reset"
            else:
                reply_text = "Forbidden"
        elif text.startswith("/budget"):
            reply_text = await budget_ledger.render_budget()
        elif text.startswith("/help") or text.startswith("/start"):
            reply_text = HELP_TEXT
        else:
            reply_text = "Unknown command"

        if chat_id is not None:
            await send_message(chat_id=chat_id, text=reply_text)

        return {"status": "ok"}
    except Exception:
        logger.exception("telegram_webhook_failed")
        return {"ok": True}
