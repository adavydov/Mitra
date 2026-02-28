"""Runtime pipeline: task -> report text -> Drive file -> shareable link -> Telegram confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Protocol, Sequence
from collections import Counter


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    topic: str
    findings: Sequence[str]
    audience: str


@dataclass(frozen=True)
class DriveArtifact:
    file_id: str
    web_view_link: str


class DriveClient(Protocol):
    def create_text_file(self, *, name: str, content: str, mime_type: str = "text/markdown") -> str:
        """Creates a file and returns file_id."""

    def make_shareable(self, *, file_id: str) -> None:
        """Grants read permission by link."""

    def get_web_view_link(self, *, file_id: str) -> str:
        """Returns shareable web link for file."""


class TelegramClient(Protocol):
    def send_message(self, *, chat_id: str, text: str) -> None:
        """Sends a plain text message."""


@dataclass(frozen=True)
class TaskLifecycleRecord:
    task_id: str
    mitra_detected_gaps: bool
    reached_deploy_without_manual_edits: bool
    cycles_to_merge: int | None
    missing_capabilities: Sequence[str]


@dataclass(frozen=True)
class PeriodicKPIs:
    tasks_total: int
    pct_mitra_detected_gaps: float
    pct_telegram_to_deploy_without_manual_edits: float
    median_cycles_to_merge: float
    top_recurring_missing_capabilities: list[tuple[str, int]]


@dataclass(frozen=True)
class KPIThresholds:
    min_pct_mitra_detected_gaps: float = 60.0
    min_pct_telegram_to_deploy_without_manual_edits: float = 40.0
    max_median_cycles_to_merge: float = 4.0


def build_report_text(task: ResearchTask) -> str:
    bullets = "\n".join(f"- {item}" for item in task.findings) if task.findings else "- Нет данных"
    return (
        f"# Исследовательский отчёт\n\n"
        f"**Task ID:** {task.task_id}\n"
        f"**Тема:** {task.topic}\n"
        f"**Аудитория:** {task.audience}\n\n"
        f"## Ключевые выводы\n{bullets}\n"
    )


def build_telegram_confirmation(*, task: ResearchTask, artifact_link: str) -> str:
    return (
        f"✅ Отчёт по задаче {task.task_id} создан.\n"
        f"Тема: {task.topic}\n"
        f"Ссылка на артефакт: {artifact_link}"
    )


def process_research_task_to_drive(
    *,
    task: ResearchTask,
    drive_client: DriveClient,
    telegram_client: TelegramClient,
    telegram_chat_id: str,
) -> DriveArtifact:
    """Processes research task and notifies Telegram with artifact link."""
    report_text = build_report_text(task)
    file_name = f"research-report-{task.task_id}.md"

    file_id = drive_client.create_text_file(name=file_name, content=report_text)
    drive_client.make_shareable(file_id=file_id)
    link = drive_client.get_web_view_link(file_id=file_id)

    telegram_text = build_telegram_confirmation(task=task, artifact_link=link)
    telegram_client.send_message(chat_id=telegram_chat_id, text=telegram_text)

    return DriveArtifact(file_id=file_id, web_view_link=link)


def _safe_percentage(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100, 2)


def calculate_periodic_kpis(records: Sequence[TaskLifecycleRecord], *, top_n: int = 5) -> PeriodicKPIs:
    total = len(records)
    mitra_detected_count = sum(1 for item in records if item.mitra_detected_gaps)
    full_automation_count = sum(1 for item in records if item.reached_deploy_without_manual_edits)
    merge_cycles = [item.cycles_to_merge for item in records if item.cycles_to_merge is not None]

    missing_capabilities_counter: Counter[str] = Counter()
    for item in records:
        missing_capabilities_counter.update(capability.strip() for capability in item.missing_capabilities if capability.strip())

    return PeriodicKPIs(
        tasks_total=total,
        pct_mitra_detected_gaps=_safe_percentage(mitra_detected_count, total),
        pct_telegram_to_deploy_without_manual_edits=_safe_percentage(full_automation_count, total),
        median_cycles_to_merge=float(median(merge_cycles)) if merge_cycles else 0.0,
        top_recurring_missing_capabilities=missing_capabilities_counter.most_common(top_n),
    )


def detect_kpi_degradation_alerts(kpis: PeriodicKPIs, thresholds: KPIThresholds) -> list[str]:
    alerts: list[str] = []
    if kpis.pct_mitra_detected_gaps < thresholds.min_pct_mitra_detected_gaps:
        alerts.append(
            f"⚠️ KPI degradation: % задач с self-detected gaps = {kpis.pct_mitra_detected_gaps}% "
            f"(threshold >= {thresholds.min_pct_mitra_detected_gaps}%)"
        )
    if kpis.pct_telegram_to_deploy_without_manual_edits < thresholds.min_pct_telegram_to_deploy_without_manual_edits:
        alerts.append(
            f"⚠️ KPI degradation: % задач Telegram→Deploy без ручных правок = "
            f"{kpis.pct_telegram_to_deploy_without_manual_edits}% "
            f"(threshold >= {thresholds.min_pct_telegram_to_deploy_without_manual_edits}%)"
        )
    if kpis.median_cycles_to_merge > thresholds.max_median_cycles_to_merge:
        alerts.append(
            f"⚠️ KPI degradation: median cycles-to-merge = {kpis.median_cycles_to_merge} "
            f"(threshold <= {thresholds.max_median_cycles_to_merge})"
        )
    return alerts


def build_periodic_audit_report_text(
    *,
    period: str,
    owner: str,
    kpis: PeriodicKPIs,
    alerts: Sequence[str],
    template_path: str = "reports/templates/periodic_audit_report.md",
) -> str:
    prepared_at = datetime.now(timezone.utc).isoformat()
    top_capabilities = (
        "\n".join(f"- {capability}: {count}" for capability, count in kpis.top_recurring_missing_capabilities)
        if kpis.top_recurring_missing_capabilities
        else "- none"
    )
    alerts_text = "\n".join(f"- {item}" for item in alerts) if alerts else "- No KPI degradation detected"

    template = Path(template_path).read_text(encoding="utf-8")
    replacements = {
        "<YYYY-MM-DD .. YYYY-MM-DD>": period,
        "<timestamp UTC>": prepared_at,
        "<team/person>": owner,
        "<pct_mitra_detected_gaps>": f"{kpis.pct_mitra_detected_gaps}%",
        "<pct_telegram_to_deploy_without_manual_edits>": f"{kpis.pct_telegram_to_deploy_without_manual_edits}%",
        "<median_cycles_to_merge>": str(kpis.median_cycles_to_merge),
        "<top_recurring_missing_capabilities>": top_capabilities,
        "<kpi_alerts>": alerts_text,
    }
    for source, value in replacements.items():
        template = template.replace(source, value)
    return template


def publish_periodic_audit_report(
    *,
    period: str,
    owner: str,
    records: Sequence[TaskLifecycleRecord],
    drive_client: DriveClient,
    telegram_client: TelegramClient,
    telegram_chat_id: str,
    thresholds: KPIThresholds = KPIThresholds(),
    template_path: str = "reports/templates/periodic_audit_report.md",
) -> DriveArtifact:
    kpis = calculate_periodic_kpis(records)
    alerts = detect_kpi_degradation_alerts(kpis, thresholds)
    report_text = build_periodic_audit_report_text(
        period=period,
        owner=owner,
        kpis=kpis,
        alerts=alerts,
        template_path=template_path,
    )
    file_name = f"periodic-audit-report-{period.replace(' ', '_').replace('/', '-')}.md"
    file_id = drive_client.create_text_file(name=file_name, content=report_text)
    drive_client.make_shareable(file_id=file_id)
    link = drive_client.get_web_view_link(file_id=file_id)

    alert_suffix = f"\nAlerts: {len(alerts)}" if alerts else "\nAlerts: none"
    telegram_client.send_message(
        chat_id=telegram_chat_id,
        text=f"📊 Periodic audit report published for {period}.\nLink: {link}{alert_suffix}",
    )

    return DriveArtifact(file_id=file_id, web_view_link=link)
