"""M11 — Retrieval contract models.

Defines the internal contracts for retrieval hits, fused candidates,
and retrieval trace used across all retrieval channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RetrievalSource(str, Enum):
    """Which retrieval channel produced a hit."""

    DENSE = "dense"
    LEXICAL = "lexical"
    GRAPH = "graph"


class RetrievalMode(str, Enum):
    """Search mode for the hybrid retriever."""

    DENSE = "dense"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


@dataclass
class RetrievalHit:
    """A single retrieval hit from one channel.

    Each retriever produces hits with a channel-specific rank and score.
    The rank is 1-based (1 = best).
    """

    memory_id: str
    source: RetrievalSource
    source_rank: int  # 1-based rank within this source
    source_score: float  # Raw score from this retriever (0-1 range for dense/lexical)


@dataclass
class FusedCandidate:
    """A candidate memory after RRF fusion across retrieval channels.

    Retains per-channel provenance for trace/explainability.
    """

    memory_id: str
    rrf_score: float  # Final RRF fused score

    # Per-channel rank/score (None if not present in that channel)
    dense_rank: int | None = None
    dense_score: float | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    graph_rank: int | None = None
    graph_score: float | None = None

    # Number of channels that returned this candidate
    channel_count: int = 0


@dataclass
class RetrieverTrace:
    """Trace of one retriever's results for explainability."""

    source: RetrievalSource
    candidate_count: int
    hits: list[RetrievalHit] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None


@dataclass
class HybridRetrievalResult:
    """Result of hybrid retrieval before Munin ranking.

    Contains fused candidates sorted by RRF score and per-channel traces.
    """

    candidates: list[FusedCandidate]
    traces: list[RetrieverTrace]
    total_unique_candidates: int = 0
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
