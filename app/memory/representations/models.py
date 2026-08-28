"""M10 — Hierarchical representation models.

Defines the representation levels and selection context used by the
representation service and context assembly pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RepresentationLevel(str, Enum):
    """Available representation levels for a memory."""

    L0_GIST = "L0"       # One-line gist (~20-30 tokens)
    L1_SUMMARY = "L1"    # Compact summary (~60-150 tokens)
    L2_FULL = "L2"       # Authoritative full content


@dataclass
class RepresentationResult:
    """Result of building representations for a single memory."""

    gist: str | None       # L0
    summary: str | None    # L1
    # L2 is always memory.content — not stored here
    provider: str          # Which provider generated these (e.g. "deterministic")
    generated: bool        # True if representations were actually generated


@dataclass
class RepresentationSelection:
    """The outcome of choosing which representation level to use."""

    level: RepresentationLevel
    text: str
    token_cost: int
    selection_reason: str


@dataclass
class ContextState:
    """State information needed for representation selection.

    This captures the relevant context assembly state without coupling
    to the full assembler internals.
    """

    token_budget: int
    remaining_budget: int
    memories_selected: int
    max_memories: int
    query: str
    # Future: could add total_candidate_count, importance_threshold, etc.


# Token limit defaults (configurable via Settings)
L0_MAX_TOKENS: int = 50
L1_MAX_TOKENS: int = 200
L0_MAX_CHARS: int = 120
L1_MAX_CHARS: int = 600
