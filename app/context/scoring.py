"""Hybrid ranking signals for context assembly.

M6 decay integration
--------------------
When ``decay_enabled=True`` on ``ContextConfig``, the ``importance`` component
of the ranking formula uses **effective importance** (stored_importance × decay
multiplier) rather than raw stored importance.

This means memories whose type decays quickly (events, ephemeral) lose relevance
with age, while project / goal / preference memories retain relevance longer.

Stored importance is NEVER mutated by this path.
The M5 recency signal (small ``exp(-λ*age)`` factor) is kept as a *separate*
short-range query-time signal — it is NOT the same as the decay multiplier.
Both signals together avoid double-penalising old memories more than intended:
decay acts on the importance component; recency acts on its own small component.
"""

from __future__ import annotations

import math
from datetime import datetime

from app.context.models import ContextConfig, ReasonCode, ScoredCandidate
from app.decay.calculator import compute_effective_importance
from app.models.memory import Memory, MemoryType


CONTINUATION_KEYWORDS = frozenset(
    {
        "continue",
        "building",
        "build",
        "project",
        "left",
        "munin",
        "help",
        "working",
        "where",
        "off",
    }
)

TYPE_BASE_SCORES: dict[MemoryType, float] = {
    MemoryType.project: 1.0,
    MemoryType.goal: 0.95,
    MemoryType.decision: 0.9,
    MemoryType.procedure: 0.85,
    MemoryType.fact: 0.8,
    MemoryType.preference: 0.75,
    MemoryType.relationship: 0.5,
    MemoryType.event: 0.35,
    MemoryType.other: 0.5,
}

CONTINUATION_TYPES = frozenset(
    {
        MemoryType.project,
        MemoryType.goal,
        MemoryType.decision,
        MemoryType.procedure,
        MemoryType.fact,
        MemoryType.preference,
    }
)


def is_continuation_query(query: str) -> bool:
    tokens = set(query.lower().split())
    return bool(tokens & CONTINUATION_KEYWORDS) or any(
        phrase in query.lower() for phrase in ("left off", "continue from")
    )


def _to_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware (SQLite may return naive datetimes)."""
    from datetime import UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def compute_recency_score(
    created_at: datetime,
    as_of: datetime,
    *,
    lambda_: float,
) -> float:
    """Bounded recency signal — query-time only, no persistent decay."""
    age_seconds = max(0.0, (_to_utc(as_of) - _to_utc(created_at)).total_seconds())
    age_days = age_seconds / 86400.0
    return math.exp(-lambda_ * age_days)


def compute_type_relevance(query: str, memory_type: MemoryType) -> float:
    """Deterministic type priority without an LLM query classifier."""
    base = TYPE_BASE_SCORES.get(memory_type, 0.5)
    if is_continuation_query(query):
        if memory_type in CONTINUATION_TYPES:
            return base
        if memory_type == MemoryType.event:
            return 0.2
    return base * 0.85


def compute_reinforcement_score(reinforcement_count: int) -> float:
    """
    Bounded boost from M3 reinforcement provenance.

    Repetition must not dominate semantic relevance.
    """
    if reinforcement_count <= 0:
        return 0.0
    return min(0.8, 0.2 + 0.15 * math.log1p(reinforcement_count))


def compute_final_score(
    *,
    semantic_score: float,
    importance: float,
    confidence: float,
    recency_score: float,
    type_relevance: float,
    reinforcement_score: float,
    config: ContextConfig,
) -> float:
    """Centralized experimental ranking formula."""
    return (
        semantic_score * config.weight_semantic
        + importance * config.weight_importance
        + confidence * config.weight_confidence
        + recency_score * config.weight_recency
        + type_relevance * config.weight_type_relevance
        + reinforcement_score * config.weight_reinforcement
    )


def build_reason_codes(
    *,
    semantic_score: float,
    importance: float,
    recency_score: float,
    type_relevance: float,
    reinforcement_score: float,
) -> list[str]:
    codes: list[str] = []
    if semantic_score >= 0.7:
        codes.append(ReasonCode.HIGH_SEMANTIC_RELEVANCE.value)
    if importance >= 0.8:
        codes.append(ReasonCode.HIGH_IMPORTANCE.value)
    if recency_score >= 0.8:
        codes.append(ReasonCode.RECENT.value)
    if reinforcement_score >= 0.25:
        codes.append(ReasonCode.REINFORCED.value)
    if type_relevance >= 0.9:
        codes.append(ReasonCode.TYPE_RELEVANT.value)
    return codes


def score_candidate(
    *,
    memory: Memory,
    semantic_score: float,
    reinforcement_count: int,
    query: str,
    as_of: datetime,
    config: ContextConfig,
) -> ScoredCandidate:
    """Score one memory candidate for context ranking.

    When ``config.decay_enabled`` is True, the importance component uses
    effective_importance = stored_importance × decay_multiplier × reinforcement_modifier.

    The reinforcement signal in the final_score formula is then computed
    from the remaining M5 reinforcement score (log-based boost separate from
    the decay reinforcement modifier — they serve different roles: the decay
    modifier boosts the decayed importance fractionally; the M5 reinforcement
    score is a standalone small bonus).

    Stored importance is NEVER written back.
    """
    recency = compute_recency_score(memory.created_at, as_of, lambda_=config.recency_lambda)
    type_rel = compute_type_relevance(query, memory.memory_type)
    reinforcement = compute_reinforcement_score(reinforcement_count)

    if config.decay_enabled:
        from app.config import get_settings
        settings = get_settings()
        importance_for_ranking = compute_effective_importance(
            stored_importance=memory.importance,
            memory_type=memory.memory_type,
            created_at=memory.created_at,
            as_of=as_of,
            reinforcement_count=reinforcement_count,
            settings=settings,
        )
    else:
        importance_for_ranking = memory.importance

    final = compute_final_score(
        semantic_score=semantic_score,
        importance=importance_for_ranking,
        confidence=memory.confidence,
        recency_score=recency,
        type_relevance=type_rel,
        reinforcement_score=reinforcement,
        config=config,
    )
    codes = build_reason_codes(
        semantic_score=semantic_score,
        importance=importance_for_ranking,
        recency_score=recency,
        type_relevance=type_rel,
        reinforcement_score=reinforcement,
    )
    return ScoredCandidate(
        memory=memory,
        semantic_score=round(semantic_score, 6),
        importance=round(importance_for_ranking, 6),   # effective, not stored
        confidence=memory.confidence,
        recency_score=round(recency, 6),
        type_relevance=round(type_rel, 6),
        reinforcement_score=round(reinforcement, 6),
        final_score=round(final, 6),
        reason_codes=codes,
    )


def sort_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """Stable deterministic ordering."""
    return sorted(
        candidates,
        key=lambda item: (
            -item.final_score,
            -item.memory.created_at.timestamp(),
            item.memory.id,
        ),
    )
