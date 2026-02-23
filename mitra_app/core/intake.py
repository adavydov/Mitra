from __future__ import annotations


def classify(text: str) -> str:
    t = (text or "").strip().lower()
    if any(x in t for x in ["hack", "взлом", "обойти", "steal"]):
        return "restricted"
    if t.startswith("/status"):
        return "status"
    if t.startswith("/report"):
        return "report"
    if t.startswith("/help") or t.startswith("/start"):
        return "help"
    return "unknown"
