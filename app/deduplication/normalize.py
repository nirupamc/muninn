"""Safe text normalization for exact-duplicate detection."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_for_exact_match(text: str) -> str:
    """
    Conservative normalization for exact/near-exact duplicates.

    - trim leading/trailing whitespace
    - collapse repeated whitespace
    - case-fold

    Does not strip punctuation or rewrite meaning.
    """
    collapsed = _WHITESPACE.sub(" ", (text or "").strip())
    return collapsed.casefold()
