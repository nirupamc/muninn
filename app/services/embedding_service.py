"""Embedding application service."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.embeddings.vector_utils import (
    cosine_similarity,
    deserialize_vector,
    serialize_vector,
)
from app.models.embedding import MemoryEmbedding
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.embedding_repository import EmbeddingRepository
from app.schemas.memory import MemoryRead, MemorySearchRequest, MemorySearchResponse, MemorySearchResult

logger = logging.getLogger("munin.embeddings")


class EmbeddingService:
    """Embed memories and run semantic retrieval."""

    def __init__(
        self,
        db: Session,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.repo = EmbeddingRepository(db)
        self.provider = provider or get_embedding_provider()

    def embed_memory(self, memory: Memory, *, commit: bool = False) -> MemoryEmbedding:
        """Generate and persist an embedding for a memory."""
        try:
            vector = self.provider.embed_text(memory.content)
        except EmbeddingError as exc:
            logger.error(
                "Embedding failed memory_id=%s provider=%s model=%s",
                memory.id,
                self.provider.provider_name,
                self.provider.model_name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding model could not be loaded or used",
            ) from exc

        if len(vector) != self.provider.dimension:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Embedding dimension mismatch",
            )

        row = self.repo.upsert(
            memory_id=memory.id,
            provider=self.provider.provider_name,
            model_name=self.provider.model_name,
            dimension=self.provider.dimension,
            embedding=serialize_vector(vector),
            commit=commit,
        )
        logger.info(
            "Embedded memory_id=%s provider=%s model=%s dimension=%s",
            memory.id,
            row.provider,
            row.model_name,
            row.dimension,
        )
        return row

    def backfill_missing(self) -> dict[str, int]:
        """Embed all memories that do not yet have an embedding. Idempotent."""
        missing = self.repo.list_unembedded_memories()
        embedded = 0
        failed = 0
        for memory in missing:
            try:
                self.embed_memory(memory, commit=True)
                embedded += 1
            except Exception:  # noqa: BLE001
                self.db.rollback()
                failed += 1
                logger.error("Backfill failed memory_id=%s", memory.id)

        return {
            "scanned_missing": len(missing),
            "embedded": embedded,
            "failed": failed,
        }

    def search(self, payload: MemorySearchRequest) -> MemorySearchResponse:
        try:
            query_vector = self.provider.embed_text(payload.query)
        except EmbeddingError as exc:
            logger.error(
                "Query embedding failed provider=%s model=%s",
                self.provider.provider_name,
                self.provider.model_name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding model could not be loaded or used",
            ) from exc

        candidates = self.repo.list_search_candidates(
            namespace=payload.namespace,
            provider=self.provider.provider_name,
            model_name=self.provider.model_name,
            dimension=self.provider.dimension,
            user_id=payload.user_id,
            # agent_id intentionally ignored at repo level for cross-agent sharing;
            # we filter in-service if explicitly requested.
            agent_id=None,
            memory_types=payload.memory_types,
            statuses=payload.statuses,
        )

        scored: list[tuple[Memory, float]] = []
        for memory, embedding_row in candidates:
            # Apply agent_id filter if requested (repo doesn't filter for cross-agent sharing)
            if payload.agent_id is not None and memory.agent_id != payload.agent_id:
                continue
            stored = deserialize_vector(embedding_row.embedding)
            score = cosine_similarity(query_vector, stored)
            if score >= payload.min_score:
                scored.append((memory, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        top = scored[: payload.limit]

        results = [
            MemorySearchResult(
                memory=MemoryRead.model_validate(memory),
                score=round(score, 6),
            )
            for memory, score in top
        ]

        logger.info(
            "Semantic search namespace=%s candidates=%s results=%s",
            payload.namespace,
            len(candidates),
            len(results),
        )

        return MemorySearchResponse(
            query=payload.query,
            namespace=payload.namespace,
            count=len(results),
            results=results,
        )
