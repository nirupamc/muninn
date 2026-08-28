"""M11 — Dense retriever adapter.

Wraps existing semantic/vector retrieval behind a common RetrievalHit
interface without rewriting the underlying algorithm.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.embeddings.base import EmbeddingProvider
from app.embeddings.vector_utils import cosine_similarity, deserialize_vector
from app.models.memory import MemoryStatus, MemoryType
from app.repositories.embedding_repository import EmbeddingRepository
from app.retrieval.models import RetrievalHit, RetrievalSource, RetrieverTrace

logger = logging.getLogger("munin.retrieval.dense")


class DenseRetriever:
    """Dense (vector/semantic) retrieval channel.

    Wraps the existing EmbeddingRepository.list_search_candidates +
    cosine similarity computation. Does NOT rewrite the algorithm.
    """

    def __init__(
        self,
        db: Session,
        provider: EmbeddingProvider,
    ) -> None:
        self.db = db
        self.provider = provider
        self._embedding_repo = EmbeddingRepository(db)

    def search(
        self,
        *,
        query: str,
        namespace: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        include_superseded: bool = False,
        limit: int = 50,
    ) -> tuple[list[RetrievalHit], RetrieverTrace]:
        """Run dense retrieval and return hits + trace.

        Returns hits sorted by descending cosine similarity (best first).
        """
        t_start = datetime.now()

        try:
            query_vector = self.provider.embed_text(query)
        except Exception as exc:
            logger.warning("Dense retrieval embed failed: %s", exc)
            trace = RetrieverTrace(
                source=RetrievalSource.DENSE,
                candidate_count=0,
                error=str(exc),
                elapsed_seconds=0.0,
            )
            return [], trace

        statuses = (
            [MemoryStatus.active, MemoryStatus.superseded]
            if include_superseded
            else [MemoryStatus.active]
        )

        raw_candidates = self._embedding_repo.list_search_candidates(
            namespace=namespace,
            provider=self.provider.provider_name,
            model_name=self.provider.model_name,
            dimension=self.provider.dimension,
            user_id=user_id,
            agent_id=agent_id,
            memory_types=memory_types,
            statuses=statuses,
        )

        scored: list[tuple[str, float]] = []
        for memory, embedding_row in raw_candidates:
            stored_vec = deserialize_vector(embedding_row.embedding)
            sem_score = float(cosine_similarity(query_vector, stored_vec))
            scored.append((memory.id, sem_score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        hits: list[RetrievalHit] = []
        for rank, (memory_id, score) in enumerate(scored[:limit], start=1):
            hits.append(
                RetrievalHit(
                    memory_id=memory_id,
                    source=RetrievalSource.DENSE,
                    source_rank=rank,
                    source_score=round(score, 6),
                )
            )

        elapsed = (datetime.now() - t_start).total_seconds()
        trace = RetrieverTrace(
            source=RetrievalSource.DENSE,
            candidate_count=len(raw_candidates),
            hits=hits,
            elapsed_seconds=round(elapsed, 4),
        )

        logger.info(
            "Dense retrieval namespace=%s candidates=%d hits=%d elapsed=%.3fs",
            namespace,
            len(raw_candidates),
            len(hits),
            elapsed,
        )

        return hits, trace
