"""M11 — Graph retriever using temporal/dedup relationship data.

Leverages existing MemoryTemporalDecision and MemoryDeduplicationDecision
data to find related memories via bounded graph traversal.

Design:
- Seed from high-confidence dense/lexical hits (not standalone)
- Traverse bounded relevant relationships
- Return related candidate memories with graph distance/type
- Strict bounds: max depth 2, candidate limit 20
- Never cross namespace boundaries
- Superseded truth must not accidentally outrank active truth
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.deduplication import MemoryDeduplicationDecision, MemoryReinforcement
from app.models.memory import MemoryStatus
from app.models.temporal import MemoryTemporalDecision
from app.retrieval.models import RetrievalHit, RetrievalSource, RetrieverTrace

logger = logging.getLogger("munin.retrieval.graph")

# Graph traversal limits
MAX_DEPTH = 2
MAX_CANDIDATES = 20


class GraphRetriever:
    """Graph retrieval channel using temporal/dedup relationships.

    Given seed memory IDs, traverses relationship edges to find
    related memories. Does NOT perform standalone retrieval —
    it augments dense/lexical results with graph-adjacent memories.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        *,
        seed_memory_ids: list[str],
        namespace: str,
        include_superseded: bool = False,
        max_depth: int = MAX_DEPTH,
        limit: int = MAX_CANDIDATES,
    ) -> tuple[list[RetrievalHit], RetrieverTrace]:
        """Traverse relationships from seed memories and return related candidates.

        Args:
            seed_memory_ids: Starting points for traversal (from dense/lexical hits).
            namespace: Namespace to stay within (never cross).
            include_superseded: Whether to include superseded memories.
            max_depth: Maximum traversal depth.
            limit: Maximum candidates to return.

        Returns:
            Related memory hits with graph rank/score.
        """
        t_start = datetime.now()

        if not seed_memory_ids:
            trace = RetrieverTrace(
                source=RetrievalSource.GRAPH,
                candidate_count=0,
                elapsed_seconds=0.0,
            )
            return [], trace

        # Collect all related memory IDs via BFS
        visited: set[str] = set(seed_memory_ids)
        frontier: set[str] = set(seed_memory_ids)
        # Map: related_memory_id → (distance, relationship_type, confidence)
        related: dict[str, tuple[int, str, float]] = {}

        for depth in range(1, max_depth + 1):
            next_frontier: set[str] = set()

            for memory_id in frontier:
                # Find temporal relationships
                temporal_edges = self._get_temporal_edges(memory_id)
                for related_id, relationship, confidence in temporal_edges:
                    if related_id in visited:
                        continue
                    # Namespace check — skip if different namespace
                    if not self._in_namespace(related_id, namespace):
                        continue
                    # Superseded check
                    if not include_superseded and self._is_superseded(related_id):
                        continue
                    visited.add(related_id)
                    next_frontier.add(related_id)
                    related[related_id] = (depth, relationship, confidence)

                # Find dedup/reinforcement relationships
                dedup_edges = self._get_dedup_edges(memory_id)
                for related_id, relationship, confidence in dedup_edges:
                    if related_id in visited:
                        continue
                    if not self._in_namespace(related_id, namespace):
                        continue
                    if not include_superseded and self._is_superseded(related_id):
                        continue
                    visited.add(related_id)
                    next_frontier.add(related_id)
                    related[related_id] = (depth, relationship, confidence)

            frontier = next_frontier
            if not frontier:
                break

        # Build hits sorted by: closer distance first, higher confidence first
        hits: list[RetrievalHit] = []
        sorted_related = sorted(
            related.items(),
            key=lambda x: (x[1][0], -x[1][2]),
        )

        for rank, (memory_id, (distance, rel_type, confidence)) in enumerate(
            sorted_related[:limit], start=1
        ):
            # Score: combine distance (closer = higher) and confidence
            # Distance 1 → 0.9, distance 2 → 0.7
            distance_score = max(0.3, 1.0 - 0.3 * (distance - 1))
            score = distance_score * confidence

            hits.append(
                RetrievalHit(
                    memory_id=memory_id,
                    source=RetrievalSource.GRAPH,
                    source_rank=rank,
                    source_score=round(score, 6),
                )
            )

        elapsed = (datetime.now() - t_start).total_seconds()
        trace = RetrieverTrace(
            source=RetrievalSource.GRAPH,
            candidate_count=len(related),
            hits=hits,
            elapsed_seconds=round(elapsed, 4),
        )

        logger.info(
            "Graph retrieval seeds=%d related=%d hits=%d elapsed=%.3fs",
            len(seed_memory_ids),
            len(related),
            len(hits),
            elapsed,
        )

        return hits, trace

    def _get_temporal_edges(self, memory_id: str) -> list[tuple[str, str, float]]:
        """Get temporal relationship edges from a memory."""
        stmt = (
            or_(
                MemoryTemporalDecision.matched_memory_id == memory_id,
                MemoryTemporalDecision.created_memory_id == memory_id,
            )
        )
        rows = self.db.query(MemoryTemporalDecision).filter(stmt).all()

        edges: list[tuple[str, str, float]] = []
        for row in rows:
            # Determine the "other" memory in the relationship
            if row.matched_memory_id == memory_id and row.created_memory_id:
                other_id = row.created_memory_id
            elif row.created_memory_id == memory_id and row.matched_memory_id:
                other_id = row.matched_memory_id
            else:
                continue

            edges.append((other_id, row.relationship, row.relationship_confidence))

        return edges

    def _get_dedup_edges(self, memory_id: str) -> list[tuple[str, str, float]]:
        """Get dedup/reinforcement edges from a memory."""
        # Reinforcement links
        reinfs = (
            self.db.query(MemoryReinforcement)
            .filter(
                or_(
                    MemoryReinforcement.memory_id == memory_id,
                    MemoryReinforcement.source_event_id.in_(
                        # Find events that reinforced this memory
                        self.db.query(MemoryReinforcement.source_event_id)
                        .filter(MemoryReinforcement.memory_id == memory_id)
                        .correlate(MemoryReinforcement)
                        .scalar_subquery()
                    ),
                )
            )
            .all()
        )

        edges: list[tuple[str, str, float]] = []
        for r in reinfs:
            if r.memory_id != memory_id:
                edges.append((r.memory_id, "REINFORCEMENT", r.relationship_confidence))

        return edges

    def _in_namespace(self, memory_id: str, namespace: str) -> bool:
        """Check if a memory belongs to the given namespace."""
        from app.models.memory import Memory

        memory = self.db.get(Memory, memory_id)
        if memory is None:
            return False
        return memory.namespace == namespace

    def _is_superseded(self, memory_id: str) -> bool:
        """Check if a memory is superseded."""
        from app.models.memory import Memory

        memory = self.db.get(Memory, memory_id)
        if memory is None:
            return True  # Non-existent = skip
        return memory.status == MemoryStatus.superseded
