"""Detect explicit state-change language in memory candidates.

M3 must not collapse change-of-state statements as duplicates merely because
they share vocabulary with an existing memory. Such candidates are preserved
as M3 NEW so M4 temporal analysis can classify UPDATES / CONTRADICTS / SUPERSEDES.

Continuity phrases (still, remains, continues to) express reinforcement — not
state change — and must not trigger this boundary.
"""

from __future__ import annotations

import re

# Continuity / reinforcement — not a change-of-state for M3 boundary purposes.
_CONTINUITY = re.compile(
    r"(?i)\b(?:still|remains?|continue(?:s|d)?(?:\s+to)?|as\s+always)\b"
)

# Explicit change-of-state cues deferred to M4.
_CHANGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:switched|migrated|transitioned)\b"),
    re.compile(r"(?i)\b(?:switched|migrated|moved|changed|transitioned)\s+from\b"),
    re.compile(r"(?i)\b(?:switched|migrated|moved|changed|transitioned)\s+to\b"),
    re.compile(r"(?i)\b(?:migrated|moved|changed|transitioned)\s+to\b"),
    re.compile(r"(?i)\breplaced\b"),
    re.compile(r"(?i)\breplaced\s+with\b"),
    re.compile(r"(?i)\bno\s+longer\b"),
    re.compile(r"(?i)\bstopped\s+(?:using|working\s+with)\b"),
    re.compile(r"(?i)\bstarted\s+using\b"),
    re.compile(r"(?i)\bnow\s+(?:uses?|prefers?|works?\s+with)\b"),
    re.compile(r"(?i)\bused\s+to\b"),
    re.compile(r"(?i)\banymore\b"),
    re.compile(r"(?i)\binstead\b"),
    re.compile(
        r"(?i)\b(?:do\s+not|don't|does\s+not|doesn't)\s+"
        r"(?:prefer|use|uses|using)\b[^.]*\banymore\b"
    ),
)


def _matches_change_pattern(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CHANGE_PATTERNS)


def contains_state_change_signal(text: str) -> bool:
    """
    True when *text* expresses an explicit state change, replacement, or
    temporal transition that M4 should resolve.

    Continuity-only statements (e.g. "still uses SQLite") return False.
    """
    if not text or not text.strip():
        return False

    has_change = _matches_change_pattern(text)
    if not has_change:
        return False

    # Continuity co-occurring with explicit change still counts as change
    # (e.g. rare edge cases). Continuity alone does not.
    if _CONTINUITY.search(text) and not _matches_change_pattern(text):
        return False

    return True
