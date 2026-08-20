"""Deterministic privacy / secret-like content detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patterns for obvious secret-like material. Keep conservative and local.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+"),
    re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|auth(?:orization)?|password|passwd|secret|"
        r"private[_ -]?key|db[_ -]?password|database[_ -]?url)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_\.=]{8,}"),
    re.compile(r"(?i)\bpassword\s+is\s+\S+"),
]


REDACTED_PLACEHOLDER = "[REDACTED]"


@dataclass(frozen=True)
class PrivacyCheckResult:
    is_sensitive: bool
    reason: str | None = None


def contains_secret_like_data(text: str) -> PrivacyCheckResult:
    """Return whether text appears to contain secret-like material."""
    if not text:
        return PrivacyCheckResult(is_sensitive=False)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return PrivacyCheckResult(is_sensitive=True, reason="SECRET_LIKE_DATA")
    return PrivacyCheckResult(is_sensitive=False)


def redact_if_sensitive(text: str | None) -> str | None:
    """Replace sensitive text with a safe placeholder."""
    if text is None:
        return None
    if contains_secret_like_data(text).is_sensitive:
        return REDACTED_PLACEHOLDER
    return text
