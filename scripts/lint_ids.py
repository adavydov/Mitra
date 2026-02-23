#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^ID:\s*([A-Z0-9-]+)\s*$")
DEP_RE = re.compile(r"^Depends on:\s*(.*)$")
HEADER_REQUIRED = ["ID:", "Level:", "Owner:", "Status:", "Depends on:"]


def main() -> int:
    ids = {}
    depends_refs = defaultdict(list)
    errors: list[str] = []

    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        rel = path.relative_to(ROOT)
        if any(rel.parts[0] == p for p in ["governance", "policy", "protocols", "runbooks", "capabilities"]):
            head = text[:20]
            for req in HEADER_REQUIRED:
                if not any(line.startswith(req) for line in head):
                    errors.append(f"{rel}: missing header field {req}")
        for line in text:
            m = ID_RE.match(line.strip())
            if m:
                ident = m.group(1)
                if ident in ids:
                    errors.append(f"duplicate ID {ident} in {rel} and {ids[ident]}")
                ids[ident] = str(rel)
            dm = DEP_RE.match(line.strip())
            if dm:
                refs = [x.strip() for x in dm.group(1).split(",") if x.strip() and x.strip() != "(empty)" and x.strip() != "None"]
                for ref in refs:
                    depends_refs[ref].append(str(rel))

    for ref, locs in depends_refs.items():
        if ref not in ids:
            errors.append(f"unknown Depends on ID {ref} referenced in {', '.join(locs)}")

    if errors:
        print("lint_ids failed")
        for e in errors:
            print("-", e)
        return 1
    print(f"lint_ids ok: {len(ids)} IDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
