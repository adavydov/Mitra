from __future__ import annotations

import os
import re
import subprocess
import sys
from fnmatch import fnmatch

RESTRICTED_PATTERNS = ("governance/*", ".github/workflows/*", "policy/*")
OVERRIDE_LABELS = {"sovereign-override", "l0-approved"}
HIGH_RISK_LABELS = {"security-review", "governance-approved"}


def _extract_section_items(body: str, heading: str) -> list[str]:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return []

    tail = body[match.end() :]
    next_heading = re.search(r"^##\s+", tail, flags=re.MULTILINE)
    section = tail[: next_heading.start()] if next_heading else tail

    items: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value.lower() != "(none)":
                items.append(value)
    return items


def _git_changed_files(base_sha: str, head_sha: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    pr_body = os.getenv("PR_BODY", "")
    labels_csv = os.getenv("PR_LABELS", "")
    base_sha = os.getenv("PR_BASE_SHA", "")
    head_sha = os.getenv("PR_HEAD_SHA", "")

    if not base_sha or not head_sha:
        print("ERROR: PR_BASE_SHA/PR_HEAD_SHA are required")
        return 2

    labels = {item.strip().lower() for item in labels_csv.split(",") if item.strip()}
    allowed_scope = _extract_section_items(pr_body, "Allowed file scope")
    risk_items = _extract_section_items(pr_body, "Risk level")
    risk_level = (risk_items[0].upper() if risk_items else "R2")

    if not allowed_scope:
        print("ERROR: PR body must include '## Allowed file scope' with bullet items")
        return 1

    changed_files = _git_changed_files(base_sha=base_sha, head_sha=head_sha)
    restricted_touched = [
        path for path in changed_files if any(fnmatch(path, pattern) for pattern in RESTRICTED_PATTERNS)
    ]
    out_of_scope = [path for path in changed_files if not any(fnmatch(path, pat) for pat in allowed_scope)]

    if out_of_scope:
        print("ERROR: changed files are outside declared Allowed file scope:")
        for path in out_of_scope:
            print(f" - {path}")
        return 1

    if restricted_touched and not labels.intersection(OVERRIDE_LABELS):
        print("ERROR: restricted scope touched without override label (sovereign-override/l0-approved):")
        for path in restricted_touched:
            print(f" - {path}")
        return 1

    if risk_level in {"R3", "R4"} or restricted_touched:
        missing = [label for label in sorted(HIGH_RISK_LABELS) if label not in labels]
        if missing:
            print(f"ERROR: high-risk change requires approval labels: {', '.join(sorted(HIGH_RISK_LABELS))}")
            print(f"Missing: {', '.join(missing)}")
            return 1

    print("Scope check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
