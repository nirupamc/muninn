"""Deterministic baseline representation provider (M10).

Generates L0 (gist) and L1 (summary) from authoritative memory content
without any external LLM dependency. This is the primary provider — it
must always work as long as the memory content is non-empty.

Design principles:
- L0: One concise sentence, preserving critical identifiers
- L1: Compact summary preserving key clauses and identifiers
- Both are bounded in length and deterministic (same input → same output)
- Identifiers like function names, paths, and technical terms are preserved
"""

from __future__ import annotations

import re

from app.memory.representations.models import (
    L0_MAX_CHARS,
    L1_MAX_CHARS,
    RepresentationResult,
)


def _extract_first_sentence(content: str) -> str:
    """Extract the first meaningful sentence from content.

    Handles common patterns:
    - 'Subject verb object.'
    - 'Project X commit: "message"'
    - Content with leading labels like 'Agent session summary:'
    """
    text = content.strip()

    # Strip common leading labels
    label_prefixes = [
        "Agent session summary:",
        "Agent session summary\\n",
        "Project .* commit:",
        "Recent project files changed:",
    ]
    for prefix in label_prefixes:
        text = re.sub(rf"^{prefix}\s*", "", text, count=1, flags=re.IGNORECASE)

    text = text.strip()

    if not text:
        return ""

    # Try to find the first sentence (ends with . ! ? or newline followed by capital)
    # But also handle short content that is already one clause
    sentences = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)
    if sentences:
        first = sentences[0].strip()
        if first:
            return first

    # Fallback: take first line
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if line:
            return line

    return text


def _truncate_at_word(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, breaking at word boundary when possible."""
    if len(text) <= max_chars:
        return text

    # Try to break at last space before limit
    truncated = text[:max_chars]
    last_space = truncated.rfind(' ')
    if last_space > max_chars * 0.6:  # Don't break too early
        return truncated[:last_space].rstrip()
    return truncated.rstrip()


def _build_gist(content: str) -> str | None:
    """Generate an L0 gist from memory content.

    Rules:
    - One concise sentence
    - Preserve critical identifiers (function names, file paths, etc.)
    - Bounded to L0_MAX_CHARS
    - Deterministic
    """
    content = content.strip()
    if not content:
        return None

    # Extract first meaningful sentence
    gist = _extract_first_sentence(content)

    if not gist:
        return None

    # Truncate to L0 bounds
    gist = _truncate_at_word(gist, L0_MAX_CHARS)

    # Clean up trailing punctuation if we truncated mid-sentence
    gist = gist.rstrip(',:;-')

    return gist if gist else None


def _build_summary(content: str) -> str | None:
    """Generate an L1 summary from memory content.

    Rules:
    - Preserve important clauses and identifiers
    - Include key technical terms, function names, paths
    - Bounded to L1_MAX_CHARS
    - Deterministic

    Strategy:
    1. Extract the most important lines (non-empty, non-boilerplate)
    2. Join them preserving original order
    3. Truncate at word boundary
    """
    content = content.strip()
    if not content:
        return None

    lines = content.split('\n')

    # Filter to meaningful lines (non-empty, not just whitespace or punctuation)
    meaningful: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines that are just formatting
        if stripped in ('---', '===', '***', '```', '---'):
            continue
        meaningful.append(stripped)

    if not meaningful:
        return None

    # Join meaningful lines, preserving order
    summary = ' '.join(meaningful)

    # Truncate to L1 bounds
    summary = _truncate_at_word(summary, L1_MAX_CHARS)

    # Clean up trailing punctuation
    summary = summary.rstrip(',:;-')

    return summary if summary else None


def generate_representations(content: str) -> RepresentationResult:
    """Generate L0 gist and L1 summary from authoritative memory content.

    This is the deterministic baseline — no LLM required.
    Returns a result with both representations (or None if generation fails).
    Memory content is NEVER modified.
    """
    if not content or not content.strip():
        return RepresentationResult(
            gist=None,
            summary=None,
            provider="deterministic",
            generated=False,
        )

    try:
        gist = _build_gist(content)
        summary = _build_summary(content)
        return RepresentationResult(
            gist=gist,
            summary=summary,
            provider="deterministic",
            generated=True,
        )
    except Exception:
        # Representation generation must never crash the caller
        return RepresentationResult(
            gist=None,
            summary=None,
            provider="deterministic",
            generated=False,
        )
