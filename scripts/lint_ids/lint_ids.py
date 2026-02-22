#!/usr/bin/env python3
"""Validate ID declarations and cross-document references.

Supported markers in text files:
- ID: <TOKEN>
- REF: <TOKEN>
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCAN_GLOBS = ["**/*.md", "**/*.txt", "**/*.yaml", "**/*.yml", "**/*.json"]
SKIP_PARTS = {".git", ".github"}
ID_PATTERN = re.compile(r"\bID:\s*([A-Z0-9][A-Z0-9\-_.]*)")
REF_PATTERN = re.compile(r"\bREF:\s*([A-Z0-9][A-Z0-9\-_.]*)")


def iter_files() -> list[pathlib.Path]:
    files: set[pathlib.Path] = set()
    for glob in SCAN_GLOBS:
        files.update(ROOT.glob(glob))
    selected = []
    for path in sorted(files):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        selected.append(path)
    return selected


def main() -> int:
    id_locations: dict[str, list[str]] = defaultdict(list)
    refs: list[tuple[str, str]] = []

    for file_path in iter_files():
        rel = file_path.relative_to(ROOT)
        text = file_path.read_text(encoding="utf-8", errors="ignore")

        for idx, line in enumerate(text.splitlines(), start=1):
            for match in ID_PATTERN.finditer(line):
                ident = match.group(1)
                id_locations[ident].append(f"{rel}:{idx}")
            for match in REF_PATTERN.finditer(line):
                refs.append((match.group(1), f"{rel}:{idx}"))

    failures: list[str] = []

    for ident, locations in sorted(id_locations.items()):
        if len(locations) > 1:
            failures.append(f"Duplicate ID {ident}: {', '.join(locations)}")

    known_ids = set(id_locations)
    for ref, location in refs:
        if ref not in known_ids:
            failures.append(f"Unknown REF {ref} at {location}")

    if failures:
        print("ID lint failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print(f"ID lint passed. IDs={len(known_ids)} Refs={len(refs)} Files={len(iter_files())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
