"""Memory application service."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.embeddings.base import EmbeddingProvider
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.event_repository import EventRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import MemoryCreate, MemorySearchRequest, MemorySearchResponse, MemoryUpdate
from app.services.embedding_service import EmbeddingService


class MemoryService:
    """Memory operations with embedding lifecycle integration."""

    def __init__(
        self,
        db: Session,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.repo = MemoryRepository(db)
        self.event_repo = EventRepository(db)
        self.embedding_service = EmbeddingService(db, provider=embedding_provider)

    def create(self, payload: MemoryCreate) -> Memory:
        if payload.source_event_id is not None:
            source = self.event_repo.get_by_id(payload.source_event_id)
            if source is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"source_event_id '{payload.source_event_id}' does not exist",
                )

        memory = Memory(
            namespace=payload.namespace,
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            content=payload.content,
            memory_type=payload.memory_type,
            importance=payload.importance,
            confidence=payload.confidence,
            status=payload.status,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            source_event_id=payload.source_event_id,
            metadata_=payload.metadata,
        )

        try:
            memory = self.repo.create(memory, commit=False)
            self.embedding_service.embed_memory(memory, commit=False)
            self.db.commit()
            self.db.refresh(memory)
            return memory
        except Exception:
            self.db.rollback()
            raise

    def get(self, memory_id: str) -> Memory:
        memory = self.repo.get_by_id(memory_id)
        if memory is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Memory '{memory_id}' not found",
            )
        return memory

    def list(
        self,
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        return self.repo.list(
            namespace=namespace,
            user_id=user_id,
            agent_id=agent_id,
            memory_type=memory_type,
            status=status,
            limit=limit,
            offset=offset,
        )

    def update(self, memory_id: str, payload: MemoryUpdate) -> Memory:
        memory = self.get(memory_id)
        updates = payload.model_dump(exclude_unset=True)

        # Map API field "metadata" onto ORM attribute "metadata_"
        if "metadata" in updates:
            updates["metadata_"] = updates.pop("metadata")

        # If only one temporal bound is being patched, validate against existing value.
        valid_from = updates.get("valid_from", memory.valid_from)
        valid_until = updates.get("valid_until", memory.valid_until)
        if valid_from is not None and valid_until is not None and valid_until < valid_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="valid_until must be greater than or equal to valid_from",
            )

        content_changed = "content" in updates and updates["content"] != memory.content

        try:
            memory = self.repo.update(memory, updates, commit=False)
            if content_changed:
                self.embedding_service.embed_memory(memory, commit=False)
            self.db.commit()
            self.db.refresh(memory)
            return memory
        except Exception:
            self.db.rollback()
            raise

    def delete(self, memory_id: str) -> None:
        memory = self.get(memory_id)
        # Embedding rows are removed via ON DELETE CASCADE.
        self.repo.delete(memory)

    def search(self, payload: MemorySearchRequest) -> MemorySearchResponse:
        return self.embedding_service.search(payload)
