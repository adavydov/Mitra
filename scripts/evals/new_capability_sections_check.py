#!/usr/bin/env python3
"""CI check for mandatory new capability sections in rendered task issue markdown."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mitra_app.main import _render_task_issue
REQUIRED_HEADINGS = [
    "## Missing capabilities",
    "## Required code changes (paths/modules)",
    "## Policy/config updates",
    "## Acceptance checks",
    "## Rollback/safety",
    "## CI completeness block",
]


def extract_ci_payload(body: str) -> dict[str, object]:
    match = re.search(r"## CI completeness block\n```json\n(\{.*?\})\n```", body, flags=re.DOTALL)
    if not match:
        raise AssertionError("missing machine-checkable CI completeness JSON block")
    return json.loads(match.group(1))


def main() -> int:
    _, body = _render_task_issue(
        {
            "title": "Capability",
            "summary": "Add new capability",
            "task_type": "new capability",
            "missing_capabilities": ["No /hello command"],
            "required_code_changes": ["mitra_app/main.py"],
            "policy_config_updates": ["policy/merge_rules.md"],
            "acceptance_checks": ["pytest tests/test_telegram_webhook.py -k task"],
            "rollback_safety": ["Feature flag rollback path"],
        }
    )

    for heading in REQUIRED_HEADINGS:
        if heading not in body:
            raise AssertionError(f"missing heading: {heading}")

    payload = extract_ci_payload(body)
    if payload.get("task_type") != "new capability":
        raise AssertionError("unexpected task_type in CI payload")
    if payload.get("mandatory_sections_complete") is not True:
        raise AssertionError("mandatory_sections_complete must be true for filled sections")

    mandatory_sections = payload.get("mandatory_sections")
    if not isinstance(mandatory_sections, dict) or not mandatory_sections:
        raise AssertionError("mandatory_sections must be non-empty object")

    if not all(value is True for value in mandatory_sections.values()):
        raise AssertionError("all mandatory sections must be true for filled sample")

    print("OK: new capability sections check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
