"""Lightweight PII redaction for prompts before they leave the cluster.

Aim is conservative: catch the common identifiers (email, phone, Aadhaar,
PAN, generic credit-card-shaped numbers) without trying to be a full DLP
system. Callers opt in via ``redact_pii=True`` on ``chat_completion``.

The regexes are intentionally readable, not maximally strict. False positives
are preferable to leaks for the things we redact.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# International + Indian mobile shapes; caller's name is "+91 98xxxxxxxx" etc.
_PHONE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}\b")
# Aadhaar: 12 digits in 4-4-4 groups (or solid)
_AADHAAR = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# PAN: AAAAA9999A
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
# Credit-card-shaped 13-19 digit runs with optional separators
_CARD = re.compile(r"\b(?:\d[\s-]?){13,19}\b")


def redact_pii(text: str) -> str:
    """Return ``text`` with common PII patterns replaced by placeholder tokens.

    Order matters: redact more-specific patterns (Aadhaar, PAN) before the
    catch-all phone / card regexes so we don't double-tag.
    """
    if not text:
        return text
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _AADHAAR.sub("[REDACTED_AADHAAR]", text)
    text = _PAN.sub("[REDACTED_PAN]", text)
    text = _CARD.sub("[REDACTED_CARD]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    return text
