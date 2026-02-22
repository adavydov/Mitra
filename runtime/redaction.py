"""PII redaction helpers for logs."""

from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
PHONE_RE = re.compile(r"\+?\d[\d\s()\-]{7,}\d")
LONG_NUMBER_RE = re.compile(r"\b\d{8,}\b")
TOKEN_RE = re.compile(r"\b([A-Za-z0-9]{4,})\b")


def _mask_email(match: re.Match) -> str:
    return f"{match.group(1)}***{match.group(3)}"


def _mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) < 6:
        return "***"
    return f"+{digits[:1]}******{digits[-4:]}"


def _mask_long_number(match: re.Match) -> str:
    number = match.group(0)
    return f"{'*' * (len(number) - 2)}{number[-2:]}"


def redact_text(text: str) -> str:
    redacted = EMAIL_RE.sub(_mask_email, text)
    redacted = PHONE_RE.sub(_mask_phone, redacted)
    redacted = LONG_NUMBER_RE.sub(_mask_long_number, redacted)

    # Very simple token-like masking for long alnum sequences.
    def mask_token(m: re.Match) -> str:
        value = m.group(1)
        if len(value) >= 16:
            return f"{value[:4]}...{value[-4:]}"
        return value

    return TOKEN_RE.sub(mask_token, redacted)
