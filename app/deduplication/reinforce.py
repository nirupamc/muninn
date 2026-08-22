"""Reinforcement signal detection for deduplication."""

from __future__ import annotations

import re

# Cues that indicate the user is confirming/reinforcing an existing memory.
# Conservative: only strong, unambiguous confirmation language escalates an
# exact-match candidate out of the cheap DUPLICATE path so it can be classified
# as REINFORCES. Words like "again" are intentionally excluded because they are
# frequently used in plain restatements ("building it again") that are duplicates.
_REINFORCE_CUES = re.compile(
    r"(?i)\b(?:yes|correct|exactly|still|remains?|continue(?:s|d)?(?:|\s+to)|"
    r"as\s+always|confirmed|confirms)\b"
)


def contains_reinforcement_signal(text: str) -> bool:
    """Return whether text contains language indicating reinforcement/confirmation."""
    if not text:
        return False
    return bool(_REINFORCE_CUES.search(text))