"""Evidence layer keeps minimal audit trail for processed events."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def record(event: Dict[str, Any], status: str, note: str) -> None:
    log_path = Path(os.getenv("EVIDENCE_LOG_PATH", "./data/evidence.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event.get("id"),
        "event_type": event.get("type"),
        "status": status,
        "note": note,
    }

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
