from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class DriveClient:
    def __init__(self, enabled: bool, folder_id: str) -> None:
        self.enabled = enabled
        self.folder_id = folder_id

    def create_report(self, report_text: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, "Drive disabled"
        Path("audit").mkdir(exist_ok=True)
        name = f"drive-artifact-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.md"
        path = Path("audit") / name
        path.write_text(report_text, encoding="utf-8")
        return True, f"drive://{self.folder_id}/{name}"
