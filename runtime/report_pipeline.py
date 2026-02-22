"""Runtime pipeline: task -> report text -> Drive file -> shareable link -> Telegram confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


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
