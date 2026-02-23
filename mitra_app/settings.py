from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    telegram_webhook_secret: str
    allowed_user_ids: set[int]
    autonomy_level: str
    risk_appetite: str
    budget_daily_limit: int
    capabilities: dict[str, bool]
    drive_enabled: bool
    drive_folder: str


def _read_json(path: str) -> dict:
    fp = Path(path)
    if not fp.exists():
        return {}
    return json.loads(fp.read_text(encoding="utf-8"))


def load_settings() -> Settings:
    tool_permissions = _read_json("config/tool_permissions.json")
    budget_cfg = _read_json("config/budget.json")
    aut_cfg = _read_json("config/autonomy.json")
    risk_cfg = _read_json("config/risk.json")

    allow_cfg = _read_json("config/allowlist.json")
    cfg_ids = (((allow_cfg.get("telegram") or {}).get("allowed_user_ids")) or [])
    allowed_raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
    env_ids = [int(v.strip()) for v in allowed_raw.split(",") if v.strip().isdigit()]
    allowed = {int(v) for v in cfg_ids if str(v).isdigit()} | set(env_ids)

    caps = {
        "telegram": bool(tool_permissions.get("telegram", False)),
        "drive": bool(tool_permissions.get("drive", False)),
        "github": bool(tool_permissions.get("github", False)),
        "render": bool(tool_permissions.get("render", False)),
    }

    return Settings(
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        allowed_user_ids=allowed,
        autonomy_level=os.getenv("AUTONOMY_LEVEL", aut_cfg.get("default_level", "AL1")),
        risk_appetite=os.getenv("RISK_APPETITE", risk_cfg.get("default_level", "R1")),
        budget_daily_limit=int(os.getenv("BUDGET_DAILY_LIMIT", budget_cfg.get("daily_limit", 0))),
        capabilities=caps,
        drive_enabled=bool(os.getenv("GOOGLE_DRIVE_FOLDER_ID")),
        drive_folder=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
    )
