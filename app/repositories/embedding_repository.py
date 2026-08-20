"""Embedding persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.embedding import MemoryEmbedding
from app.models.memory import Memory, MemoryStatus, MemoryType


class EmbeddingRepository:
    """Data-access layer for memory embeddings."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_memory_id(self, memory_id: str) -> MemoryEmbedding | None:
        stmt = select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
        return self.db.scalars(stmt).first()

    def upsert(
        self,
        *,
        memory_id: str,
        provider: str,
        model_name: str,
        dimension: int,
        embedding: bytes,
        commit: bool = False,
    ) -> MemoryEmbedding:
        existing = self.get_by_memory_id(memory_id)
        now = datetime.now(UTC)
        if existing is None:
            row = MemoryEmbedding(
                memory_id=memory_id,
                provider=provider,
                model_name=model_name,
                dimension=dimension,
                embedding=embedding,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row = existing
            row.provider = provider
            row.model_name = model_name
            row.dimension = dimension
            row.embedding = embedding
            row.updated_at = now
            self.db.add(row)

        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row

    def delete_by_memory_id(self, memory_id: str, *, commit: bool = False) -> None:
        row = self.get_by_memory_id(memory_id)
        if row is None:
            return
        self.db.delete(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    def list_unembedded_memories(self) -> list[Memory]:
        stmt = (
            select(Memory)
            .outerjoin(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(MemoryEmbedding.id.is_(None))
            .order_by(Memory.created_at.asc())
        )
        return list(self.db.scalars(stmt).all())

    def list_search_candidates(
        self,
        *,
        namespace: str,
        provider: str,
        model_name: str,
        dimension: int,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        statuses: list[MemoryStatus] | None = None,
    ) -> list[tuple[Memory, MemoryEmbedding]]:
        """
        Return (memory, embedding) pairs for semantic search.

        Only embeddings matching the active provider/model/dimension are included.
        """
        stmt = (
            select(Memory, MemoryEmbedding)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(Memory.namespace == namespace)
            .where(MemoryEmbedding.provider == provider)
            .where(MemoryEmbedding.model_name == model_name)
            .where(MemoryEmbedding.dimension == dimension)
        )
        if user_id is not None:
            stmt = stmt.where(Memory.user_id == user_id)
        if agent_id is not None:
            stmt = stmt.where(Memory.agent_id == agent_id)
        if memory_types:
            stmt = stmt.where(Memory.memory_type.in_(memory_types))
        if statuses:
            stmt = stmt.where(Memory.status.in_(statuses))

        return list(self.db.execute(stmt).all())
