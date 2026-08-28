"""M11 — Reciprocal Rank Fusion (RRF).

Fuses ranked results from multiple retrieval channels into a single
ranking using the RRF formula:

    RRF(d) = Σ 1 / (k + rank_i(d))

where k is a constant (default 60) that controls how much lower-ranked
documents are penalized.

Design:
- RRF uses ranks, not incomparable raw scores
- A memory appearing in multiple channels gains appropriate fused relevance
- k is configurable (default 60, standard in literature)
"""

from __future__ import annotations

from app.retrieval.models import (
    FusedCandidate,
    HybridRetrievalResult,
    RetrievalHit,
    RetrievalSource,
    RetrievalMode,
    RetrieverTrace,
)

# Default RRF constant
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    channel_hits: dict[RetrievalSource, list[RetrievalHit]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[FusedCandidate]:
    """Fuse hits from multiple retrieval channels using RRF.

    Args:
        channel_hits: Map of source → hits (already ranked within each source).
        k: RRF constant (higher = less penalty for lower ranks).

    Returns:
        Fused candidates sorted by RRF score descending.
    """
    # Accumulate RRF scores per memory_id
    scores: dict[str, float] = {}
    # Track per-channel rank/score for provenance
    dense_rank: dict[str, int] = {}
    dense_score: dict[str, float] = {}
    lexical_rank: dict[str, int] = {}
    lexical_score: dict[str, float] = {}
    graph_rank: dict[str, int] = {}
    graph_score: dict[str, float] = {}
    channel_counts: dict[str, int] = {}

    for source, hits in channel_hits.items():
        for hit in hits:
            mid = hit.memory_id
            # RRF contribution: 1 / (k + rank)
            rrf_contribution = 1.0 / (k + hit.source_rank)
            scores[mid] = scores.get(mid, 0.0) + rrf_contribution
            channel_counts[mid] = channel_counts.get(mid, 0) + 1

            # Record per-channel provenance
            if source == RetrievalSource.DENSE:
                dense_rank[mid] = hit.source_rank
                dense_score[mid] = hit.source_score
            elif source == RetrievalSource.LEXICAL:
                lexical_rank[mid] = hit.source_rank
                lexical_score[mid] = hit.source_score
            elif source == RetrievalSource.GRAPH:
                graph_rank[mid] = hit.source_rank
                graph_score[mid] = hit.source_score

    # Build fused candidates sorted by RRF score descending
    candidates = []
    for mid, rrf_score in scores.items():
        candidates.append(
            FusedCandidate(
                memory_id=mid,
                rrf_score=round(rrf_score, 6),
                dense_rank=dense_rank.get(mid),
                dense_score=dense_score.get(mid),
                lexical_rank=lexical_rank.get(mid),
                lexical_score=lexical_score.get(mid),
                graph_rank=graph_rank.get(mid),
                graph_score=graph_score.get(mid),
                channel_count=channel_counts.get(mid, 0),
            )
        )

    # Sort by RRF score descending, then by memory_id for determinism
    candidates.sort(key=lambda c: (-c.rrf_score, c.memory_id))

    return candidates


def build_hybrid_result(
    dense_hits: list[RetrievalHit],
    lexical_hits: list[RetrievalHit],
    graph_hits: list[RetrievalHit],
    dense_trace: RetrieverTrace,
    lexical_trace: RetrieverTrace,
    graph_trace: RetrieverTrace,
    *,
    k: int = DEFAULT_RRF_K,
    mode: RetrievalMode = RetrievalMode.HYBRID,
) -> HybridRetrievalResult:
    """Build a complete HybridRetrievalResult from channel results.

    Selects which channels participate based on the retrieval mode.
    """
    channel_hits: dict[RetrievalSource, list[RetrievalHit]] = {}
    traces: list[RetrieverTrace] = []

    if mode == RetrievalMode.DENSE:
        channel_hits[RetrievalSource.DENSE] = dense_hits
        traces.append(dense_trace)
    elif mode == RetrievalMode.LEXICAL:
        channel_hits[RetrievalSource.LEXICAL] = lexical_hits
        traces.append(lexical_trace)
    else:  # HYBRID
        if dense_hits:
            channel_hits[RetrievalSource.DENSE] = dense_hits
        if lexical_hits:
            channel_hits[RetrievalSource.LEXICAL] = lexical_hits
        if graph_hits:
            channel_hits[RetrievalSource.GRAPH] = graph_hits
        traces.extend([dense_trace, lexical_trace, graph_trace])

    fused = reciprocal_rank_fusion(channel_hits, k=k)

    return HybridRetrievalResult(
        candidates=fused,
        traces=traces,
        total_unique_candidates=len(fused),
        retrieval_mode=mode,
    )
