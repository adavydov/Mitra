from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass
class TrackedTask:
    issue_number: int
    chat_id: int
    created_at: str
    last_notified_state: str | None = None


class TaskTrackerStore:
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock = Lock()

    def load(self) -> list[TrackedTask]:
        with self._lock:
            return self._load_unlocked()

    def add(self, issue_number: int, chat_id: int) -> None:
        with self._lock:
            tasks = self._load_unlocked()
            if any(task.issue_number == issue_number for task in tasks):
                return
            tasks.append(
                TrackedTask(
                    issue_number=issue_number,
                    chat_id=chat_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    last_notified_state=None,
                )
            )
            self._save_unlocked(tasks)

    def update_last_notified_state(self, issue_number: int, state: str) -> None:
        with self._lock:
            tasks = self._load_unlocked()
            changed = False
            for task in tasks:
                if task.issue_number == issue_number:
                    task.last_notified_state = state
                    changed = True
                    break
            if changed:
                self._save_unlocked(tasks)

    def _load_unlocked(self) -> list[TrackedTask]:
        if not self._state_path.exists():
            return []

        payload: Any = json.loads(self._state_path.read_text(encoding="utf-8"))
        items = payload.get("tracked_tasks") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        tasks: list[TrackedTask] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            issue_number = raw.get("issue_number")
            chat_id = raw.get("chat_id")
            created_at = raw.get("created_at")
            if not isinstance(issue_number, int) or not isinstance(chat_id, int) or not isinstance(created_at, str):
                continue
            last_state = raw.get("last_notified_state")
            tasks.append(
                TrackedTask(
                    issue_number=issue_number,
                    chat_id=chat_id,
                    created_at=created_at,
                    last_notified_state=last_state if isinstance(last_state, str) else None,
                )
            )
        return tasks

    def _save_unlocked(self, tasks: list[TrackedTask]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tracked_tasks": [asdict(task) for task in tasks]}
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
