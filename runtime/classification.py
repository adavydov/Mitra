"""Classification layer for Telegram intake."""

from __future__ import annotations

import re
from typing import Literal

Classification = Literal["report_document_request", "unknown", "restricted"]

RESTRICTED_PATTERNS = [
    r"\b(malware|ransomware|keylogger|phishing)\b",
    r"\b(взлом|взломать|обойти\s+защит|краж[ау]\s+данных)\b",
    r"\b(exfiltrat(e|ion)|credential\s+steal)\b",
]

REPORT_DOC_PATTERNS = [
    r"\b(отч[её]т|документ|справк[ау]|резюме|pdf|docx?)\b",
    r"\b(подготовь|сделай|создай|сформируй|напиши)\b",
    r"\b(report|summary|document)\b",
]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify_request(text: str) -> Classification:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown"

    if any(re.search(pattern, normalized) for pattern in RESTRICTED_PATTERNS):
        return "restricted"

    has_doc_keyword = any(re.search(pattern, normalized) for pattern in REPORT_DOC_PATTERNS[:1])
    has_intent_keyword = any(re.search(pattern, normalized) for pattern in REPORT_DOC_PATTERNS[1:2])
    has_english = any(re.search(pattern, normalized) for pattern in REPORT_DOC_PATTERNS[2:])

    if (has_doc_keyword and has_intent_keyword) or has_english:
        return "report_document_request"

    return "unknown"
