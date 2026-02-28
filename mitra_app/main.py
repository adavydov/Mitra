import json
import hashlib
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
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
_GOAL_PREVIEW_MAX_CHARS = 160
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
    "/report <text>, /pr <title>\\n<spec>, /task <request>, /pr_status <issue#|pr#>, /drive_check, /budget, "
    "/smoke, /smoke_deep"
)

_TASK_SYSTEM_PROMPT = (
    "Ты переводишь пользовательскую задачу в codex-ready спецификацию issue для GitHub. "
    "Верни только JSON-объект с ключами: title, summary, components, required_env_secrets, "
    "new_commands, acceptance_criteria, tests_to_add, risk_level, allowed_file_scope. "
    "components/new_commands/required_env_secrets/acceptance_criteria/tests_to_add/allowed_file_scope должны быть массивами строк. "
    "risk_level должен быть одним из R0,R1,R2,R3,R4. "
    "required_env_secrets указывай только именами переменных без значений."
)

_TASK_RETRY_SYSTEM_PROMPT = (
    "Ты переводишь пользовательскую задачу в codex-ready спецификацию issue для GitHub. "
    "Ответь строго одним валидным JSON-объектом и ничем больше. "
    "Запрещены markdown-блоки, комментарии, пояснения, префиксы/суффиксы текста. "
    "Ключи JSON: title, summary, components, required_env_secrets, new_commands, "
    "acceptance_criteria, tests_to_add, risk_level, allowed_file_scope. "
    "components/new_commands/required_env_secrets/acceptance_criteria/tests_to_add/allowed_file_scope — массивы строк. "
    "risk_level — одно из R0,R1,R2,R3,R4. "
    "required_env_secrets указывай только именами переменных без значений."
)

_TASK_EXAMPLE_HINT = (
    "Тестовый кейс для полного цикла: /task Добавь команду /hello которая отвечает \"hello from mitra\" "
    "и покрыта тестом."
)

_TASK_CONTEXT_COMPLETENESS_THRESHOLD = 3
_TASK_CONTEXT_FIELD_ORDER = (
    "provider",
    "credentials_source",
    "risk_constraints",
    "success_criteria",
    "deadlines",
)
_TASK_CONTEXT_QUESTIONS = {
    "provider": "Уточни provider: где будем создавать задачу (например GitHub/Jira/Linear)?",
    "credentials_source": "Где брать credentials (источник секретов/доступов)?",
    "risk_constraints": "Какие есть risk constraints (например max risk level, ограничения по данным/продакшену)?",
    "success_criteria": "Сформулируй success criteria (как поймём, что задача выполнена).",
    "deadlines": "Есть ли deadline/срок для задачи?",
}


_REFLECT_SYSTEM_PROMPT = (
    "Ты формируешь только EVO-0 отчёт для человека-оператора в режиме AL0. "
    "Не выполняй действия, не вызывай инструменты и не предлагай автозапуски. "
    "Верни только итоговый отчёт без chain-of-thought."
)

_CAPABILITY_CATALOG_PATH = Path(__file__).resolve().parents[1] / "capabilities" / "catalog.json"
_CAPABILITY_GAPS_REPORT_PATH = "reports/capability_gaps.md"
_GAP_REPEAT_THRESHOLD = 3
_GAP_REPEAT_WINDOW_DAYS = 14
_CAPABILITY_GAP_TYPES: tuple[str, ...] = ("code", "policy", "config", "tests", "secrets", "runbook")
_INTENT_TOKEN_RE = re.compile(r"[a-zа-я0-9_+-]{3,}", re.IGNORECASE)

_FAILURE_REASON_TO_GAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(test|pytest|unit test|integration test|assert)\b", re.IGNORECASE), "tests_missing"),
    (re.compile(r"\b(policy|permission|allowlist|forbidden|unauthorized|compliance)\b", re.IGNORECASE), "policy_mismatch"),
    (re.compile(r"\b(env|secret|token|key|credential|missing variable|not configured)\b", re.IGNORECASE), "env_missing"),
    (re.compile(r"\b(timeout|flaky|race|intermittent|network|connection reset)\b", re.IGNORECASE), "infra_instability"),
    (re.compile(r"\b(lint|format|type check|mypy|ruff|black)\b", re.IGNORECASE), "quality_gate"),
]



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

    return _cap_output_chars(_final_only_sanitize(llm_reply), _THINK_OUTPUT_MAX_CHARS)


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

    return _final_only_sanitize("\n".join(parts).strip())


def _cap_output_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


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
    stripped = text.strip()
    if not stripped:
        return ""

    parts = stripped.split(maxsplit=1)
    command = parts[0]
    if command != "/think":
        return ""
    if len(parts) == 1:
        return ""
    return parts[1].strip()[:240]


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
    "/search": CommandPolicy(required_al="AL1", risk_level="R1", budget_category="search"),
    "/llm_check": CommandPolicy(required_al="AL2", risk_level="R1", budget_category="llm"),
    "/goal": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/goal set": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/think": CommandPolicy(required_al="AL1", risk_level="R1", budget_category="llm"),
    "/reports": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/research": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="llm"),
    "/report": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/pr_status": CommandPolicy(required_al="AL1", risk_level="R1", budget_category="search"),
    "/task": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="github"),
    "/pr": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="github"),
    "/evo_issue": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="github"),
    "/drive_check": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
    "/budget_reset_day": CommandPolicy(required_al="AL3", risk_level="R3", budget_category="search"),
    "/budget": CommandPolicy(required_al="AL1", risk_level="R0", budget_category="search"),
    "/reflect": CommandPolicy(required_al="AL2", risk_level="R2", budget_category="drive"),
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


@dataclass
class MissingContext:
    provider: str | None = None
    credentials_source: str | None = None
    risk_constraints: str | None = None
    success_criteria: str | None = None
    deadlines: str | None = None

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        for field_name in _TASK_CONTEXT_FIELD_ORDER:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                missing.append(field_name)
        return missing

    def filled_fields_count(self) -> int:
        return len(_TASK_CONTEXT_FIELD_ORDER) - len(self.missing_fields())


@dataclass
class TaskDialogState:
    request_text: str
    context: MissingContext = field(default_factory=MissingContext)
    last_question_field: str | None = None
    turns: list[dict[str, str]] = field(default_factory=list)


_task_dialog_state_by_chat: dict[int, TaskDialogState] = {}


def _extract_missing_context(request_text: str) -> MissingContext:
    text = request_text.strip()
    lowered = text.lower()
    context = MissingContext()

    provider_match = re.search(r"\b(github|gitlab|jira|linear|asana)\b", lowered)
    if provider_match:
        context.provider = provider_match.group(1)

    if any(token in lowered for token in ("vault", "1password", "secret", "env", "переменн")):
        context.credentials_source = text

    if re.search(r"\br[0-4]\b", lowered) or "risk" in lowered or "огранич" in lowered:
        context.risk_constraints = text

    if any(token in lowered for token in ("критер", "acceptance", "готово", "должен", "должна")):
        context.success_criteria = text

    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", lowered) or "дедлайн" in lowered or "до " in lowered:
        context.deadlines = text

    return context


def _merge_context_answer(state: TaskDialogState, answer_text: str) -> None:
    answer = answer_text.strip()
    if not answer:
        return

    target_field = state.last_question_field
    if target_field in _TASK_CONTEXT_FIELD_ORDER:
        setattr(state.context, target_field, answer)
    else:
        for field_name in state.context.missing_fields():
            setattr(state.context, field_name, answer)
            break

    state.turns.append({"role": "user", "content": answer})


def _build_context_question(context: MissingContext) -> tuple[str, str] | None:
    missing = context.missing_fields()
    if not missing:
        return None
    field_name = missing[0]
    question = _TASK_CONTEXT_QUESTIONS.get(field_name)
    if not question:
        return None
    return field_name, question


def _context_above_threshold(context: MissingContext) -> bool:
    return context.filled_fields_count() >= _TASK_CONTEXT_COMPLETENESS_THRESHOLD


def _enrich_task_request_with_context(request_text: str, context: MissingContext) -> str:
    lines = [request_text.strip(), "", "Контекст уточнений:"]
    for field_name in _TASK_CONTEXT_FIELD_ORDER:
        value = getattr(context, field_name)
        if isinstance(value, str) and value.strip():
            label = field_name.replace("_", " ")
            lines.append(f"- {label}: {value.strip()}")
    return "\n".join(lines).strip()


def _parse_goal_command(text: str) -> tuple[str, str | None] | None:
    normalized = text.strip()
    if normalized == "/goal":
        return "show", None
    if normalized.startswith("/goal set"):
        goal_text = normalized[len("/goal set") :].strip()
        return "set", goal_text or None
    return None


def _truncate_goal_preview(goal_text: str, limit: int | None = None) -> str:
    if limit is None:
        limit = _GOAL_PREVIEW_MAX_CHARS
    if len(goal_text) <= limit:
        return goal_text
    return f"{goal_text[:limit].rstrip()}…"


def _goal_state_from_audit() -> dict[str, str] | None:
    audit_path = Path(os.getenv("MITRA_AUDIT_LOG", "audit/audit.jsonl"))
    if not audit_path.exists():
        return None

    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        logger.exception("goal_audit_read_failed", extra={"path": str(audit_path)})
        return None

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") != "telegram_goal_set" or payload.get("outcome") != "success":
            continue

        preview = payload.get("goal_preview")
        link = payload.get("goal_link")
        goal_hash = payload.get("goal_hash")
        if isinstance(preview, str) and isinstance(link, str) and isinstance(goal_hash, str):
            return {"preview": preview, "link": link, "hash": goal_hash}

    return None


def _build_goal_show_reply() -> str:
    goal_state = _goal_state_from_audit()
    if goal_state is None:
        return "Цель не задана. Используйте /goal set <текст цели>."

    return f"Текущая цель: {goal_state['preview']}\nDrive: {goal_state['link']}"


async def _set_goal(
    *,
    goal_text: str,
    action_id: str,
    telegram_update_id: int | None,
    user_id: int | None,
    chat_id: int | None,
) -> str:
    goal_preview = _truncate_goal_preview(goal_text)
    goal_hash = hashlib.sha256(goal_text.encode("utf-8")).hexdigest()
    title = f"mitra_state-goal {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    markdown_body = (
        f"# Mitra Goal\n\n"
        f"goal:\n{goal_text}\n\n"
        f"goal_hash_sha256: {goal_hash}\n"
        f"action_id: {action_id}\n"
        f"user_id: {user_id}\n"
        f"timestamp: {datetime.now(timezone.utc).isoformat()}\n"
    )

    upload = await upload_markdown(title=title, markdown_body=markdown_body)
    goal_link = upload.web_view_link or upload.file_id
    _safe_audit_event(
        {
            "event": "telegram_goal_set",
            "action_id": action_id,
            "telegram_update_id": telegram_update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "action_type": "/goal set",
            "goal_hash": goal_hash,
            "goal_preview": goal_preview,
            "goal_link": goal_link,
            "file_id": upload.file_id,
            "outcome": "success",
            "log_level": "info",
        }
    )
    return f"Goal saved: {goal_link}"


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


def _parse_evo_issue_command(text: str) -> tuple[int, str | None] | None:
    payload = text[len("/evo_issue") :].strip()
    if not payload:
        return None

    parts = payload.split()
    if not parts:
        return None

    try:
        hypothesis_number = int(parts[0])
    except ValueError:
        return None

    if hypothesis_number <= 0:
        return None

    risk_label: str | None = None
    for part in parts[1:]:
        candidate = part.strip().lower()
        if re.fullmatch(r"risk:r[0-3]", candidate):
            risk_label = f"risk:R{candidate[-1]}"
            continue
        return None

    return hypothesis_number, risk_label


def _load_last_evo0_report() -> tuple[str, str]:
    candidates: list[Path] = []
    configured_path = os.getenv("MITRA_EVO0_REPORT_PATH", "").strip()
    if configured_path:
        candidates.append(Path(configured_path))

    reports_dir = Path("reports")
    if reports_dir.exists():
        report_files = sorted(
            reports_dir.glob("**/*"),
            key=lambda path: path.stat().st_mtime if path.is_file() else -1,
            reverse=True,
        )
        for path in report_files:
            if not path.is_file():
                continue
            name = path.name.lower()
            if "evo" in name or "governance_hierarchy_v0" in name:
                candidates.append(path)

    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content:
            return content, str(candidate)

    raise FileNotFoundError("EVO-0 report not found")


def _extract_evo_hypotheses(report_text: str) -> list[str]:
    hypotheses: list[str] = []

    try:
        payload = json.loads(report_text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        raw_items = payload.get("hypotheses")
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, str) and item.strip():
                    hypotheses.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("statement", "title", "text", "hypothesis"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            hypotheses.append(value.strip())
                            break

    if hypotheses:
        return hypotheses

    for line in report_text.splitlines():
        match = re.match(r"^\s*\d+[\.)]\s+(.+)$", line.strip())
        if match:
            hypotheses.append(match.group(1).strip())

    return hypotheses


def _build_evo_issue_body(*, hypothesis: str, report_source: str, risk_level: str) -> str:
    return (
        "## What/Why\n"
        f"- Hypothesis selected from latest EVO-0 report: {hypothesis}\n"
        "- Convert analysis into a verifiable engineering contract.\n\n"
        "## Scope\n"
        "- Implement only the minimum changes required to validate this hypothesis.\n"
        "- Keep solution aligned with mitra governance hierarchy constraints.\n\n"
        "## Acceptance criteria\n"
        "- [ ] Change is testable and tied to the selected hypothesis.\n"
        "- [ ] Bot/API behavior is explicit (no \"make it pretty\" ambiguity).\n"
        "- [ ] Audit trail records creation and execution outcomes.\n\n"
        "## Tests required\n"
        "- [ ] Unit tests for command parsing and payload construction.\n"
        "- [ ] Integration test for webhook command happy-path and failure-path.\n\n"
        f"## Risk level (R0-R3)\n- {risk_level}\n\n"
        "## Guardrails\n"
        "- Do not modify governance/* files.\n"
        "- Do not change ALLOWED_TELEGRAM_USER_IDS behavior.\n"
        "- Do not add new secrets in code or commit secrets.\n\n"
        f"_Source report: `{report_source}`_"
    )






def _parse_task_command(text: str) -> str | None:
    body = text[len("/task") :].strip()
    return body or None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    if "```" in stripped:
        block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
        if block_match:
            candidates.insert(0, block_match.group(1).strip())

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    return None


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        item_str = str(item).strip()
        if item_str:
            items.append(item_str)
    return items


def _build_fallback_task_spec(request_text: str) -> dict[str, Any]:
    summary = request_text
    title = request_text[:80].strip() or "Task from Telegram"
    return {
        "title": title,
        "summary": summary,
        "components": [],
        "required_env_secrets": [],
        "new_commands": [],
        "acceptance_criteria": [],
        "tests_to_add": [],
        "risk_level": "R2",
        "allowed_file_scope": ["mitra_app/*", "tests/*"],
        "degraded": True,
    }


_NEW_CAPABILITY_SECTION_KEYS: "OrderedDict[str, str]" = OrderedDict(
    [
        ("Missing capabilities", "missing_capabilities"),
        ("Required code changes (paths/modules)", "required_code_changes"),
        ("Policy/config updates", "policy_config_updates"),
        ("Acceptance checks", "acceptance_checks"),
        ("Rollback/safety", "rollback_safety"),
    ]
)


def _normalize_task_type(task_type: Any) -> str:
    normalized = str(task_type or "maintenance").strip().lower()
    allowed = {"new capability", "bugfix", "maintenance", "research"}
    if normalized in allowed:
        return normalized
    return "maintenance"


def _new_capability_missing_sections(spec: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for section_title, section_key in _NEW_CAPABILITY_SECTION_KEYS.items():
        values = _normalize_string_list(spec.get(section_key))
        if not values:
            missing.append(section_title)
    return missing


def _build_task_parse_diagnostics(content: Any) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"content_type": type(content).__name__}
    if not isinstance(content, list):
        return diagnostics

    text_blocks_count = 0
    non_text_block_types: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            non_text_block_types.append(type(block).__name__)
            continue

        block_type = str(block.get("type", "unknown"))
        if block_type == "text":
            text_blocks_count += 1
            continue
        non_text_block_types.append(block_type)

    diagnostics["total_blocks"] = len(content)
    diagnostics["text_blocks_count"] = text_blocks_count
    diagnostics["has_non_text_blocks"] = bool(non_text_block_types)
    diagnostics["non_text_block_types"] = sorted(set(non_text_block_types))
    return diagnostics


def _load_capability_catalog() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_CAPABILITY_CATALOG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        logger.warning("capability_catalog_unavailable", extra={"path": str(_CAPABILITY_CATALOG_PATH)})
        return []

    if not isinstance(payload, list):
        logger.warning("capability_catalog_invalid_shape", extra={"path": str(_CAPABILITY_CATALOG_PATH)})
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _extract_intents_from_request(request_text: str) -> set[str]:
    lowered = request_text.lower()
    intents: set[str] = set(_INTENT_TOKEN_RE.findall(lowered))

    intent_hints = {
        "нов": "new_capability",
        "способ": "new_capability",
        "ability": "new_capability",
        "capability": "new_capability",
        "github": "github",
        "issue": "github",
        "search": "search",
        "web": "search",
        "telegram": "telegram",
        "webhook": "telegram",
        "drive": "drive",
        "calendar": "calendar",
        "report": "reporting",
    }
    for marker, intent in intent_hints.items():
        if marker in lowered:
            intents.add(intent)
    return intents


def detect_capability_gaps(request_text: str) -> dict[str, Any]:
    intents = _extract_intents_from_request(request_text)
    catalog = _load_capability_catalog()

    matched: list[dict[str, Any]] = []
    for capability in catalog:
        capability_intents = {str(item).lower() for item in capability.get("intents", []) if str(item).strip()}
        if capability_intents.intersection(intents):
            matched.append(capability)

    if not matched:
        gaps = list(_CAPABILITY_GAP_TYPES)
        return {
            "intents": sorted(intents),
            "matched_capabilities": [],
            "gaps": gaps,
            "coverage_status": "missing",
            "gap_closure_notes": [
                f"{gap}: capability отсутствует в каталоге — требуется явная реализация/описание." for gap in gaps
            ],
        }

    has_policy = any(cap.get("policies") for cap in matched)
    has_tests = any(cap.get("tests") for cap in matched)
    has_secrets = any(cap.get("required_env") for cap in matched)
    has_code = any(cap.get("tools") for cap in matched)
    has_config = any(cap.get("tools") or cap.get("required_env") for cap in matched)
    has_runbook = any((Path(__file__).resolve().parents[1] / "runbooks" / f"{cap.get('id', '')}.md").exists() for cap in matched)

    gaps: list[str] = []
    if not has_code:
        gaps.append("code")
    if not has_policy:
        gaps.append("policy")
    if not has_config:
        gaps.append("config")
    if not has_tests:
        gaps.append("tests")
    if not has_secrets:
        gaps.append("secrets")
    if not has_runbook:
        gaps.append("runbook")

    return {
        "intents": sorted(intents),
        "matched_capabilities": [str(cap.get("id", "unknown")) for cap in matched],
        "gaps": gaps,
        "coverage_status": "covered" if not gaps else "partial",
        "gap_closure_notes": [
            (
                f"{gap}: capability частично реализована ({', '.join(str(cap.get('id', 'unknown')) for cap in matched)}) — "
                "нужно закрыть недостающий блок."
            )
            for gap in gaps
        ],
    }


def _build_gap_summary(detection: dict[str, Any]) -> str:
    gaps = _normalize_string_list(detection.get("gaps"))
    if not gaps:
        return "Gap summary: gaps не обнаружены."

    coverage_status = str(detection.get("coverage_status", "partial")).strip() or "partial"
    prefix = "missing capability" if coverage_status == "missing" else "partial capability"
    return f"Gap summary: {prefix}, закрыть блоки: {', '.join(gaps)}"


def _build_task_spec(request_text: str, llm_client: AnthropicClient | None = None) -> dict[str, Any]:
    client = llm_client or AnthropicClient(max_tokens_out=900)
    response = client.create_message(
        messages=[{"role": "user", "content": request_text}],
        system=_TASK_SYSTEM_PROMPT,
    )
    content = response.get("content")
    parse_diagnostics = _build_task_parse_diagnostics(content)
    text_blocks: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    text_blocks.append(text.strip())

    parse_diagnostics = _build_task_parse_diagnostics(content)
    parsed = _extract_json_object("\n".join(text_blocks))
    if not parsed:
        logger.warning("task_spec_parse_primary_failed", extra=parse_diagnostics)

        retry_response = client.create_message(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Верни строго JSON-объект по схеме из system prompt без markdown и комментариев.\n"
                        f"Запрос пользователя: {request_text}"
                    ),
                }
            ],
            system=_TASK_RETRY_SYSTEM_PROMPT,
        )
        retry_content = retry_response.get("content")
        retry_diagnostics = _build_task_parse_diagnostics(retry_content)
        retry_text_blocks: list[str] = []
        if isinstance(retry_content, list):
            for block in retry_content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        retry_text_blocks.append(text.strip())

        parsed = _extract_json_object("\n".join(retry_text_blocks))
        if not parsed:
            logger.warning(
                "task_spec_degraded_json_parse_failed",
                extra={
                    "parse_outcome": "fallback_used",
                    "primary_parse": parse_diagnostics,
                    "retry_parse": retry_diagnostics,
                },
            )
            logger.warning("task_spec_degraded_json_parse_failed")
            return _build_fallback_task_spec(request_text)

        logger.info(
            "task_spec_retry_success",
            extra={
                "parse_outcome": "retry_success",
                "primary_parse": parse_diagnostics,
                "retry_parse": retry_diagnostics,
            },
        )

    risk_level = str(parsed.get("risk_level", "R2")).strip().upper()
    if risk_level not in {"R0", "R1", "R2", "R3", "R4"}:
        risk_level = "R2"

    title = str(parsed.get("title", "")).strip()
    summary = str(parsed.get("summary", "")).strip()
    if not summary:
        summary = request_text
    if not title:
        title = summary[:80] or "Task from Telegram"

    return {
        "title": title,
        "summary": summary,
        "components": _normalize_string_list(parsed.get("components")),
        "required_env_secrets": _normalize_string_list(parsed.get("required_env_secrets")),
        "new_commands": _normalize_string_list(parsed.get("new_commands")),
        "acceptance_criteria": _normalize_string_list(parsed.get("acceptance_criteria")),
        "tests_to_add": _normalize_string_list(parsed.get("tests_to_add")),
        "risk_level": risk_level,
        "allowed_file_scope": _normalize_string_list(parsed.get("allowed_file_scope")) or ["mitra_app/*", "tests/*"],
        "degraded": False,
    }


def _render_task_issue(spec: dict[str, Any]) -> tuple[str, str]:
    title = str(spec.get("title", "Task from Telegram")).strip()
    summary = str(spec.get("summary", "")).strip()

    def render_list(name: str, values: list[str]) -> list[str]:
        lines = [f"## {name}"]
        if not values:
            lines.append("- (none)")
        else:
            lines.extend(f"- {value}" for value in values)
        return lines

    body_lines: list[str] = ["## Summary", summary or "(no summary)", ""]
    body_lines.extend(render_list("Components/modules to add/change", spec.get("components", [])))
    body_lines.append("")
    body_lines.extend(render_list("Required env/secrets (names only)", spec.get("required_env_secrets", [])))
    body_lines.append("")
    body_lines.extend(render_list("New commands to add", spec.get("new_commands", [])))
    body_lines.append("")
    body_lines.extend(render_list("Acceptance criteria", spec.get("acceptance_criteria", [])))
    body_lines.append("")
    body_lines.extend(render_list("Tests to add", spec.get("tests_to_add", [])))
    body_lines.append("")
    for section_title, section_key in _NEW_CAPABILITY_SECTION_KEYS.items():
        body_lines.extend(render_list(section_title, spec.get(section_key, [])))
        body_lines.append("")
    body_lines.append(f"## Risk level\n- {spec.get('risk_level', 'R2')}")
    body_lines.append("")
    body_lines.extend(render_list("Allowed file scope", spec.get("allowed_file_scope", ["mitra_app/*", "tests/*"])))

    capability_gaps = _normalize_string_list(spec.get("capability_gaps"))
    capability_gap_notes = _normalize_string_list(spec.get("capability_gap_notes"))
    if capability_gaps:
        body_lines.append("")
        body_lines.append("## Capability gaps to close")
        for idx, gap in enumerate(capability_gaps):
            body_lines.append(f"### GAP: {gap}")
            if idx < len(capability_gap_notes):
                body_lines.append(f"- {capability_gap_notes[idx]}")
            body_lines.append(f"- Закрыть системный разрыв `{gap}`: код, проверки, документация/политики по необходимости.")

    return title, "\n".join(body_lines).strip()


def _admin_chat_state_path() -> Path:
    return Path(os.getenv("MITRA_ADMIN_CHAT_STATE_PATH", "state/admin_chat_id.txt"))


def _save_admin_chat_id(chat_id: int) -> None:
    path = _admin_chat_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(chat_id), encoding="utf-8")


def _load_admin_chat_id() -> int | None:
    env_value = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            logger.warning("invalid_telegram_admin_chat_id", extra={"value": env_value})

    path = _admin_chat_state_path()
    try:
        persisted = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("failed_to_read_admin_chat_id")
        return None

    if not persisted:
        return None

    try:
        return int(persisted)
    except ValueError:
        logger.warning("invalid_persisted_admin_chat_id", extra={"value": persisted})
        return None


def _remember_admin_chat_if_allowed(user_id: int | None, chat_id: int | None, allowed_user_ids: set[int]) -> None:
    if chat_id is None or user_id is None or user_id not in allowed_user_ids:
        return
    try:
        _save_admin_chat_id(chat_id=int(chat_id))
    except (OSError, ValueError):
        logger.exception("failed_to_persist_admin_chat_id", extra={"chat_id": chat_id})

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


def _map_failure_reason_to_gap(failure_reason: str) -> str:
    reason = failure_reason.strip()
    if not reason:
        return "unknown"

    for pattern, gap_type in _FAILURE_REASON_TO_GAP:
        if pattern.search(reason):
            return gap_type
    return "other"


def _append_capability_gap_report(*, pr_number: int, pr_url: str, failure_reason: str, gap_type: str) -> None:
    path = Path(_CAPABILITY_GAPS_REPORT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Capability gaps\n\n"
            "Автогенерируемый backlog повторяющихся провалов PR/CI.\n\n"
            "| Timestamp (UTC) | PR | Gap type | Failure reason |\n"
            "|---|---:|---|---|\n",
            encoding="utf-8",
        )

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reason_cell = failure_reason.replace("\n", " ").strip() or "unspecified"
    row = f"| {timestamp} | [#{pr_number}]({pr_url}) | `{gap_type}` | {reason_cell} |\n"
    with path.open("a", encoding="utf-8") as report_file:
        report_file.write(row)


def _count_recent_gap_failures(gap_type: str, *, pr_number: int | None = None) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=_GAP_REPEAT_WINDOW_DAYS)
    count = 0
    for event in _load_recent_audit_events(limit=400):
        if event.get("event") != "github_pr_ci_status":
            continue
        if event.get("outcome") != "failed":
            continue
        if event.get("gap_type") != gap_type:
            continue

        event_ts = event.get("timestamp")
        if isinstance(event_ts, str):
            try:
                parsed_ts = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
            except ValueError:
                parsed_ts = None
            if parsed_ts and parsed_ts.tzinfo is not None and parsed_ts < since:
                continue

        if pr_number is not None and event.get("pr_number") != pr_number:
            continue
        count += 1
    return count


def _build_gap_issue_template(*, gap_type: str, failure_reason: str, pr_number: int) -> str:
    return (
        "``\n"
        f"/task Root-cause fix для gap `{gap_type}` после провалов CI в PR #{pr_number}.\n"
        "Контекст:\n"
        f"- Симптом: {failure_reason or 'unspecified'}\n"
        "- Требуется устранить корневую причину, а не только починить текущий PR.\n"
        "Acceptance criteria:\n"
        "1) Добавлен guardrail/валидация на этапе до CI.\n"
        "2) Добавлены тесты, воспроизводящие прошлый провал.\n"
        "3) Обновлена документация/политика при необходимости.\n"
        "4) В audit фиксируется снижение повторов по этому gap.\n"
        "``"
    )


async def _poll_pr_ci_snapshot(pr_number: int) -> tuple[str, str, github.GitHubPullRequestStatus | None, github.GitHubChecksSummary | None]:
    try:
        pr_status = await github.get_pr_status(pr_number)
        checks = await github.get_pr_checks_summary(pr_status.head_sha)
    except Exception:
        logger.exception("pr_ci_poll_failed", extra={"pr_number": pr_number})
        return "unknown", "", None, None

    if checks.failed > 0:
        return "failed", "ci_checks_failed", pr_status, checks
    if checks.pending > 0:
        return "pending", "checks_pending", pr_status, checks
    return "passed", "", pr_status, checks


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


def _final_only_sanitize(text: str) -> str:
    sanitized = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.IGNORECASE | re.DOTALL)
    sanitized = re.sub(r"</?thinking>", "", sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


def _extract_llm_text(response: dict[str, Any]) -> str:
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


def _audit_log_path() -> str:
    return os.getenv("MITRA_AUDIT_LOG", "audit/events.ndjson")


def _load_recent_audit_events(limit: int = 12) -> list[dict[str, Any]]:
    path = Path(_audit_log_path())
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for raw_line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if len(events) >= limit:
            break
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    events.reverse()
    return events


def _load_current_goal() -> str:
    env_goal = os.getenv("MITRA_CURRENT_GOAL", "").strip()
    if env_goal:
        return env_goal

    for event in reversed(_load_recent_audit_events(limit=60)):
        for key in ("goal", "current_goal"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "Goal is not set. Use /goal in PR-1 flow."


def _deploy_revision_hint() -> str:
    for env_name in ("MITRA_DEPLOY_VERSION", "MITRA_DEPLOY_COMMIT", "GIT_COMMIT"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return "unknown"


def _build_reflect_prompt(goal: str, audit_events: list[dict[str, Any]], budget_status: str) -> str:
    events_preview = json.dumps(audit_events, ensure_ascii=False, indent=2)
    return (
        "Собери EVO-0 отчёт по входным фактам.\n"
        f"Текущая цель:\n{goal}\n\n"
        f"Последние audit-события:\n{events_preview}\n\n"
        f"Статус бюджета:\n{budget_status}\n\n"
        f"Версия/коммит деплоя: {_deploy_revision_hint()}\n\n"
        "Требования:\n"
        "1) Дай 3-7 гипотез улучшения.\n"
        "2) Для каждой: польза, риск (R0-R3), что тестировать.\n"
        "3) Добавь раздел 'Не трогать' (например governance/*).\n"
        "4) Только предложения; ничего не выполнять."
    )


def _extract_summary_points(report_text: str, *, min_items: int = 3, max_items: int = 7) -> list[str]:
    candidates: list[str] = []
    for line in report_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = re.sub(r"^[-*•]\s+", "", stripped)
        cleaned = re.sub(r"^\d+[\.)]\s+", "", cleaned)
        if cleaned != stripped or re.match(r"^Гипотеза\s*\d+", cleaned, flags=re.IGNORECASE):
            candidates.append(cleaned)
        if len(candidates) >= max_items:
            break

    while len(candidates) < min_items:
        candidates.append("Гипотеза: уточнить узкое место по последним аудит-событиям и проверить на dry-run.")
    return candidates[:max_items]


async def _run_reflect() -> tuple[str, str, str]:
    goal = _load_current_goal()
    audit_events = _load_recent_audit_events(limit=12)
    budget_status = await budget_ledger.render_budget()
    prompt = _build_reflect_prompt(goal, audit_events, budget_status)

    payload = AnthropicClient(max_tokens_out=1200).create_message(
        messages=[{"role": "user", "content": prompt}],
        system=_REFLECT_SYSTEM_PROMPT,
    )
    await budget_ledger.record_llm_usage(payload.get("usage") if isinstance(payload, dict) else None)

    report = _final_only_sanitize(_extract_llm_text(payload))
    if not report:
        report = "# EVO-0\n\nГипотеза 1: Уточнить целевой KPI и baseline."

    summary_points = _extract_summary_points(report)
    summary = "\n".join(f"- {point}" for point in summary_points)

    title = f"mitra-evo0-reflect {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    full_report = (
        "# EVO-0 report\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Budget\n{budget_status}\n\n"
        f"## Model output\n{report}\n"
    )
    upload = await upload_markdown(title=title, markdown_body=full_report)
    await budget_ledger.record_drive_write()
    link = upload.web_view_link or upload.file_id

    reply = _final_only_sanitize(f"EVO-0 hypotheses:\n{summary}\n\nDrive: {link}")
    return reply, upload.file_id, link


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


@app.post("/github/actions_callback")
async def github_actions_callback(
    payload: dict[str, Any],
    x_mitra_actions_token: str | None = Header(default=None),
) -> dict[str, Any]:
    expected = os.getenv("GITHUB_ACTIONS_CALLBACK_TOKEN")
    if not expected or x_mitra_actions_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    admin_chat_id = _load_admin_chat_id()
    if admin_chat_id is None:
        logger.warning("github_actions_callback_missing_admin_chat")
        return {"status": "ok", "delivered": False}

    event_name = str(payload.get("event") or "").strip().lower()
    issue_number = payload.get("issue_number")
    raw_pr_number = payload.get("pr_number")
    pr_number = int(raw_pr_number) if isinstance(raw_pr_number, int) or (isinstance(raw_pr_number, str) and raw_pr_number.isdigit()) else None
    pr_url = str(payload.get("pr_url") or "").strip()
    commit_sha = payload.get("commit_sha")
    conclusion = str(payload.get("conclusion") or "").strip().lower()
    failure_reason = str(payload.get("failure_reason") or "").strip()

    polled_status: github.GitHubPullRequestStatus | None = None
    polled_checks: github.GitHubChecksSummary | None = None
    polled_outcome = "unknown"
    if pr_number is not None:
        polled_outcome, polled_reason, polled_status, polled_checks = await _poll_pr_ci_snapshot(pr_number)
        if not failure_reason and polled_outcome == "failed":
            failure_reason = polled_reason
        if not pr_url and polled_status is not None:
            pr_url = polled_status.html_url

    failed_conclusions = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
    is_failed = event_name in {"ci_failed", "pr_failed"} or conclusion in failed_conclusions or polled_outcome == "failed"
    gap_type = _map_failure_reason_to_gap(failure_reason) if is_failed else "none"

    _safe_audit_event(
        {
            "event": "github_pr_ci_status",
            "source": "github_actions_callback",
            "action_type": "github/pr_ci_status",
            "issue_number": issue_number,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "commit_sha": commit_sha,
            "event_name": event_name,
            "conclusion": conclusion,
            "outcome": "failed" if is_failed else (polled_outcome if polled_outcome != "unknown" else "updated"),
            "failure_reason": failure_reason,
            "gap_type": gap_type,
            "checks": None
            if polled_checks is None
            else {
                "total": polled_checks.total,
                "successful": polled_checks.successful,
                "failed": polled_checks.failed,
                "pending": polled_checks.pending,
            },
            "log_level": "warning" if is_failed else "info",
        }
    )

    if event_name == "pr_opened":
        text = f"PR открыт: #{pr_number} (issue #{issue_number})\n{pr_url}".strip()
    elif event_name == "pr_merged":
        text = f"PR смержен: #{pr_number}\ncommit: {commit_sha or '-'}"
    elif is_failed:
        reason_text = failure_reason or "ci_failure"
        text = f"CI/PR провал: #{pr_number or '?'}\nGap: {gap_type}\nReason: {reason_text}"
        if pr_number is not None and pr_url:
            _append_capability_gap_report(pr_number=pr_number, pr_url=pr_url, failure_reason=reason_text, gap_type=gap_type)
            repeat_count = _count_recent_gap_failures(gap_type, pr_number=pr_number)
            if repeat_count >= _GAP_REPEAT_THRESHOLD:
                text += (
                    "\n\nПовторяющийся провал. Предложенный /task шаблон:\n"
                    + _build_gap_issue_template(gap_type=gap_type, failure_reason=reason_text, pr_number=pr_number)
                )
    elif event_name in {"ci_success", "pr_checks_passed"} or conclusion == "success" or polled_outcome == "passed":
        text = f"CI зелёный: #{pr_number or '?'}\n{pr_url}".strip()
    else:
        text = f"GitHub update: {json.dumps(payload, ensure_ascii=False)}"

    await send_message(chat_id=admin_chat_id, text=text)
    return {"status": "ok", "delivered": True}


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
        if isinstance(text, str) and text.strip().startswith("/goal set"):
            action_type = "/goal set"

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

        _remember_admin_chat_if_allowed(
            user_id=user_id if isinstance(user_id, int) else None,
            chat_id=chat_id if isinstance(chat_id, int) else None,
            allowed_user_ids=allowed_user_ids,
        )

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

        pending_task_state = _task_dialog_state_by_chat.get(chat_id) if isinstance(chat_id, int) else None
        if pending_task_state is not None and isinstance(text, str) and text.strip() and not text.strip().startswith("/"):
            _merge_context_answer(pending_task_state, text)
            next_question = _build_context_question(pending_task_state.context)
            if next_question is not None and not _context_above_threshold(pending_task_state.context):
                field_name, question = next_question
                pending_task_state.last_question_field = field_name
                reply_text = question
            else:
                issue_number: int | None = None
                degraded = False
                capability_detection = {"intents": [], "matched_capabilities": [], "gaps": []}
                try:
                    enriched_request = _enrich_task_request_with_context(
                        pending_task_state.request_text,
                        pending_task_state.context,
                    )
                    spec = _build_task_spec(enriched_request)
                    degraded = bool(spec.get("degraded"))
                    capability_detection = detect_capability_gaps(pending_task_state.request_text)
                    spec["capability_gaps"] = capability_detection.get("gaps", [])
                    spec["capability_gap_notes"] = capability_detection.get("gap_closure_notes", [])
                    issue_title, issue_body = _render_task_issue(spec)
                    issue_number, issue_url = await _create_github_issue(title=issue_title, body=issue_body)
                    await budget_ledger.record_github_write()

                    required_secrets = spec.get("required_env_secrets") or []
                    expected_commands = spec.get("new_commands") or []
                    lines = [f"Issue создан: {issue_url}"]
                    if required_secrets:
                        lines.append("Требуются ключи/доступы: " + ", ".join(required_secrets))
                    if expected_commands:
                        lines.append("Ожидаемая новая команда: " + ", ".join(expected_commands))
                    detected_gaps = capability_detection.get("gaps") or []
                    if detected_gaps:
                        lines.append("Обнаружены gaps: " + ", ".join(detected_gaps))
                        lines.append(_build_gap_summary(capability_detection))
                    if degraded:
                        lines.append("Spec auto-filled from request (LLM JSON parse failed)")
                    lines.append(_TASK_EXAMPLE_HINT)
                    reply_text = "\n".join(lines)
                    outcome = "degraded" if degraded else "success"
                except Exception:
                    logger.exception("telegram_task_create_issue_failed")
                    reply_text = "Failed to create task issue"
                    outcome = "error"

                _safe_audit_event(
                    {
                        "event": "telegram_task_open_issue",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/task",
                        "issue_number": issue_number,
                        "degraded": degraded,
                        "detected_intents": capability_detection.get("intents", []),
                        "matched_capabilities": capability_detection.get("matched_capabilities", []),
                        "capability_gaps": capability_detection.get("gaps", []),
                        "outcome": outcome,
                        "log_level": "info" if outcome in {"success", "degraded"} else "error",
                    }
                )
                if isinstance(chat_id, int):
                    _task_dialog_state_by_chat.pop(chat_id, None)
        elif text.startswith("/status"):
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
        elif text.startswith("/goal"):
            goal_command = _parse_goal_command(text)
            if goal_command is None:
                reply_text = "Usage: /goal or /goal set <text>"
            else:
                goal_action, goal_value = goal_command
                if goal_action == "show":
                    reply_text = _build_goal_show_reply()
                elif goal_value is None:
                    reply_text = "Usage: /goal set <text>"
                else:
                    try:
                        reply_text = await _set_goal(
                            goal_text=goal_value,
                            action_id=action_id,
                            telegram_update_id=telegram_update_id,
                            user_id=user_id,
                            chat_id=chat_id,
                        )
                    except DriveNotConfigured:
                        reply_text = "Drive not configured for /goal set"
                        _safe_audit_event(
                            {
                                "event": "telegram_goal_set",
                                "action_id": action_id,
                                "telegram_update_id": telegram_update_id,
                                "user_id": user_id,
                                "chat_id": chat_id,
                                "action_type": "/goal set",
                                "outcome": "drive_disabled",
                                "log_level": "error",
                            }
                        )
                    except Exception:
                        logger.exception("goal_set_failed")
                        reply_text = "Goal save failed"
                        _safe_audit_event(
                            {
                                "event": "telegram_goal_set",
                                "action_id": action_id,
                                "telegram_update_id": telegram_update_id,
                                "user_id": user_id,
                                "chat_id": chat_id,
                                "action_type": "/goal set",
                                "outcome": "error",
                                "log_level": "error",
                            }
                        )
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
        elif text.startswith("/reflect"):
            file_id = ""
            try:
                reply_text, file_id, link = await _run_reflect()
                log_report_event(
                    action_id=action_id,
                    telegram_update_id=telegram_update_id,
                    file_id=file_id,
                    outcome="success",
                    user_id=user_id,
                    chat_id=chat_id,
                    link=link,
                    action_type="/reflect",
                    log_level="info",
                )
            except Exception as exc:
                logger.exception("reflect_command_failed")
                reply_text = _sanitize_report_error(exc)
                log_report_event(
                    action_id=action_id,
                    telegram_update_id=telegram_update_id,
                    file_id=file_id,
                    outcome="error",
                    user_id=user_id,
                    chat_id=chat_id,
                    action_type="/reflect",
                    log_level="error",
                )
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
        elif text.startswith("/task"):
            request_text = _parse_task_command(text)
            if not request_text:
                reply_text = "Usage: /task <request>"
            elif not _pr_rate_limiter.allow(user_id if isinstance(user_id, int) else None):
                reply_text = "Rate limit exceeded: max 5 /task per hour"
            else:
                context = _extract_missing_context(request_text)
                next_question = _build_context_question(context)
                if next_question is not None:
                    field_name, question = next_question
                    if isinstance(chat_id, int):
                        _task_dialog_state_by_chat[chat_id] = TaskDialogState(
                            request_text=request_text,
                            context=context,
                            last_question_field=field_name,
                            turns=[{"role": "user", "content": request_text}],
                        )
                    reply_text = question
                else:
                    issue_number: int | None = None
                    degraded = False
                    capability_detection = {"intents": [], "matched_capabilities": [], "gaps": []}
                    try:
                        spec = _build_task_spec(request_text)
                        degraded = bool(spec.get("degraded"))
                        capability_detection = detect_capability_gaps(request_text)
                        spec["capability_gaps"] = capability_detection.get("gaps", [])
                        spec["capability_gap_notes"] = capability_detection.get("gap_closure_notes", [])
                        issue_title, issue_body = _render_task_issue(spec)
                        issue_number, issue_url = await _create_github_issue(title=issue_title, body=issue_body)
                        await budget_ledger.record_github_write()

                        required_secrets = spec.get("required_env_secrets") or []
                        expected_commands = spec.get("new_commands") or []
                        lines = [f"Issue создан: {issue_url}"]
                        if required_secrets:
                            lines.append("Требуются ключи/доступы: " + ", ".join(required_secrets))
                        if expected_commands:
                            lines.append("Ожидаемая новая команда: " + ", ".join(expected_commands))
                        detected_gaps = capability_detection.get("gaps") or []
                        if detected_gaps:
                            lines.append("Обнаружены gaps: " + ", ".join(detected_gaps))
                            lines.append(_build_gap_summary(capability_detection))
                        if degraded:
                            lines.append("Spec auto-filled from request (LLM JSON parse failed)")
                        lines.append(_TASK_EXAMPLE_HINT)
                        reply_text = "\n".join(lines)
                        outcome = "degraded" if degraded else "success"
                    except Exception:
                        logger.exception("telegram_task_create_issue_failed")
                        reply_text = "Failed to create task issue"
                        outcome = "error"

                    _safe_audit_event(
                        {
                            "event": "telegram_task_open_issue",
                            "action_id": action_id,
                            "telegram_update_id": telegram_update_id,
                            "user_id": user_id,
                            "chat_id": chat_id,
                            "action_type": "/task",
                            "issue_number": issue_number,
                            "degraded": degraded,
                            "detected_intents": capability_detection.get("intents", []),
                            "matched_capabilities": capability_detection.get("matched_capabilities", []),
                            "capability_gaps": capability_detection.get("gaps", []),
                            "outcome": outcome,
                            "log_level": "info" if outcome in {"success", "degraded"} else "error",
                        }
                    )
        elif text.startswith("/pr"):
            parsed = _parse_pr_command(text)
            if not parsed:
                reply_text = "Usage: /pr <title>\n<spec>"
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
        elif text.startswith("/evo_issue"):
            parsed = _parse_evo_issue_command(text)
            if not parsed:
                reply_text = "Usage: /evo_issue <n> [risk:R0-R3]"
            else:
                hypothesis_number, risk_label = parsed
                issue_number: int | None = None
                issue_url: str | None = None
                try:
                    report_text, report_source = _load_last_evo0_report()
                    hypotheses = _extract_evo_hypotheses(report_text)
                    if not hypotheses or hypothesis_number > len(hypotheses):
                        reply_text = f"Hypothesis #{hypothesis_number} not found in latest EVO-0 report"
                        outcome = "not_found"
                    else:
                        selected = hypotheses[hypothesis_number - 1]
                        risk_level = risk_label.replace("risk:", "") if risk_label else "R1"
                        title = f"EVO hands: hypothesis {hypothesis_number} -> executable issue"
                        body = _build_evo_issue_body(
                            hypothesis=selected,
                            report_source=report_source,
                            risk_level=risk_level,
                        )
                        labels = ["mitra:codex"]
                        if risk_label:
                            labels.append(risk_label)

                        issue = await github.create_issue(title=title, body=body, labels=labels)
                        await budget_ledger.record_github_write()
                        issue_number = issue.number
                        issue_url = issue.html_url
                        reply_text = f"Created EVO issue: {issue_url}"
                        outcome = "success"
                except FileNotFoundError:
                    reply_text = "EVO-0 report not found"
                    outcome = "missing_report"
                except Exception:
                    logger.exception("telegram_evo_issue_create_failed")
                    reply_text = "Failed to create EVO issue"
                    outcome = "error"

                _safe_audit_event(
                    {
                        "event": "telegram_evo_issue",
                        "action_id": action_id,
                        "telegram_update_id": telegram_update_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "action_type": "/evo_issue",
                        "hypothesis_number": hypothesis_number,
                        "issue_number": issue_number,
                        "issue_url": issue_url,
                        "risk_label": risk_label,
                        "outcome": outcome,
                        "log_level": "info" if outcome in {"success", "not_found", "missing_report"} else "error",
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
