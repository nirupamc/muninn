"""Consolidation service.

Design principles
-----------------
* Source memories are NEVER deleted or superseded by consolidation.
* Consolidated memory is a NEW memory with is_consolidated marker in metadata_.
* Provenance is stored relationally in memory_consolidations + sources tables.
* The entire operation (memory + embedding + audit + source links) is atomic.
* Idempotency: identical source set → return existing consolidated memory.
* Contradictions detected by provider → refuse consolidation.
* Superseded sources excluded by default.
* Namespace + user isolation enforced.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.consolidation.base import ConsolidationProvider
from app.consolidation.models import (
    ConsolidatePreviewResponse,
    ConsolidateResponse,
    ConsolidationProposal,
    ConsolidationRead,
    SourceMemoryRead,
)
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.embeddings.vector_utils import cosine_similarity, deserialize_vector
from app.models.consolidation import MemoryConsolidation, MemoryConsolidationSource
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.consolidation_repository import ConsolidationRepository
from app.repositories.embedding_repository import EmbeddingRepository
from app.repositories.memory_repository import MemoryRepository
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger("munin.consolidation")


class ConsolidationService:
    """Orchestrate memory consolidation."""

    def __init__(
        self,
        db: Session,
        consolidation_provider: ConsolidationProvider,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.consolidation_provider = consolidation_provider
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.memory_repo = MemoryRepository(db)
        self.embedding_repo = EmbeddingRepository(db)
        self.consolidation_repo = ConsolidationRepository(db)
        self.embedding_service = EmbeddingService(db, provider=self.embedding_provider)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate(
        self,
        *,
        namespace: str,
        user_id: str | None,
        memory_ids: list[str],
        dry_run: bool = False,
    ) -> ConsolidateResponse:
        """
        Consolidate the specified memories into a derived summary memory.

        Steps:
        1. Validate source memories (exist, namespace, user, status).
        2. Check idempotency (same source set already consolidated).
        3. Run provider.
        4. If provider refuses (contradiction / low confidence), raise 422.
        5. If dry_run, return preview without persisting.
        6. Check semantic deduplication against existing consolidated memories.
        7. Atomically: create memory + embedding + audit + source links.
        """
        memories = self._validate_sources(
            namespace=namespace,
            user_id=user_id,
            memory_ids=memory_ids,
        )

        # Idempotency check
        existing = self.consolidation_repo.find_equivalent_consolidation(
            namespace=namespace,
            source_memory_ids=memory_ids,
        )
        if existing is not None:
            mem = self.memory_repo.get_by_id(existing.created_memory_id)
            if mem is not None:
                logger.info(
                    "consolidation idempotent namespace=%s existing_memory=%s",
                    namespace,
                    existing.created_memory_id,
                )
                return ConsolidateResponse(
                    consolidated_memory_id=mem.id,
                    namespace=namespace,
                    content=mem.content,
                    memory_type=mem.memory_type,
                    importance=mem.importance,
                    confidence=mem.confidence,
                    source_memory_ids=memory_ids,
                    reason="Equivalent consolidation already exists.",
                    is_new=False,
                )

        proposal = self._run_provider(memories, namespace=namespace)

        if dry_run:
            # Return proposal without writing anything
            return ConsolidateResponse(
                consolidated_memory_id="(dry-run)",
                namespace=namespace,
                content=proposal.content,
                memory_type=proposal.memory_type,
                importance=proposal.importance,
                confidence=proposal.confidence,
                source_memory_ids=memory_ids,
                reason=proposal.reason,
                is_new=True,
            )

        # Semantic dedup against existing consolidated memories
        existing_dup = self._find_semantic_duplicate(proposal, namespace=namespace)
        if existing_dup is not None:
            logger.info(
                "consolidation semantic duplicate found namespace=%s existing=%s",
                namespace,
                existing_dup.id,
            )
            return ConsolidateResponse(
                consolidated_memory_id=existing_dup.id,
                namespace=namespace,
                content=existing_dup.content,
                memory_type=existing_dup.memory_type,
                importance=existing_dup.importance,
                confidence=existing_dup.confidence,
                source_memory_ids=memory_ids,
                reason="Semantically equivalent consolidated memory already exists.",
                is_new=False,
            )

        # Atomically persist everything
        created_memory = self._persist_consolidation(
            proposal=proposal,
            namespace=namespace,
            user_id=user_id,
        )

        logger.info(
            "consolidation created namespace=%s memory_id=%s sources=%d",
            namespace,
            created_memory.id,
            len(memory_ids),
        )

        return ConsolidateResponse(
            consolidated_memory_id=created_memory.id,
            namespace=namespace,
            content=created_memory.content,
            memory_type=created_memory.memory_type,
            importance=created_memory.importance,
            confidence=created_memory.confidence,
            source_memory_ids=memory_ids,
            reason=proposal.reason,
            is_new=True,
        )

    def preview(
        self,
        *,
        namespace: str,
        user_id: str | None,
        memory_ids: list[str],
    ) -> ConsolidatePreviewResponse:
        """
        Run consolidation provider without persisting anything.

        Useful for safety review before committing.
        """
        memories = self._validate_sources(
            namespace=namespace,
            user_id=user_id,
            memory_ids=memory_ids,
        )

        proposal = self._run_provider(memories, namespace=namespace)

        # Check if equivalent already exists
        existing = self.consolidation_repo.find_equivalent_consolidation(
            namespace=namespace,
            source_memory_ids=memory_ids,
        )
        would_be_duplicate = existing is not None
        if not would_be_duplicate:
            dup = self._find_semantic_duplicate(proposal, namespace=namespace)
            would_be_duplicate = dup is not None

        return ConsolidatePreviewResponse(
            namespace=namespace,
            proposed_content=proposal.content,
            proposed_memory_type=proposal.memory_type,
            proposed_importance=proposal.importance,
            proposed_confidence=proposal.confidence,
            source_memory_ids=memory_ids,
            reason=proposal.reason,
            would_be_duplicate=would_be_duplicate,
        )

    def get_provenance(self, memory_id: str) -> ConsolidationRead | None:
        """
        Return consolidation record + sources for a consolidated memory.

        Returns None if this memory was not produced by consolidation.
        """
        record = self.consolidation_repo.get_consolidation_by_memory_id(memory_id)
        if record is None:
            return None
        return self._consolidation_to_read(record)

    def list_consolidations_for_source(self, source_memory_id: str) -> list[ConsolidationRead]:
        """Return all consolidations that used this memory as a source."""
        records = self.consolidation_repo.list_consolidations_for_source(source_memory_id)
        return [self._consolidation_to_read(r) for r in records]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_sources(
        self,
        *,
        namespace: str,
        user_id: str | None,
        memory_ids: list[str],
    ) -> list[Memory]:
        """
        Validate source memories and return them.

        Raises HTTP 422 on:
        - Empty ID list
        - Missing memory
        - Wrong namespace
        - Wrong user_id
        - Superseded / non-active status
        """
        if not memory_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="memory_ids must not be empty",
            )

        memories: list[Memory] = []
        for mid in memory_ids:
            m = self.memory_repo.get_by_id(mid)
            if m is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Memory '{mid}' not found",
                )
            if m.namespace != namespace:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Memory '{mid}' belongs to namespace '{m.namespace}', not '{namespace}'",
                )
            if user_id is not None and m.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Memory '{mid}' does not belong to user '{user_id}'",
                )
            if m.status != MemoryStatus.active:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Memory '{mid}' has status '{m.status.value}' — only active memories can be consolidated",
                )
            memories.append(m)

        return memories

    def _run_provider(
        self, memories: list[Memory], *, namespace: str
    ) -> ConsolidationProposal:
        """Run the consolidation provider; raise 422 if it refuses."""
        try:
            proposal = self.consolidation_provider.consolidate(
                memories, namespace=namespace
            )
        except Exception as exc:
            logger.error(
                "consolidation provider error provider=%s model=%s error=%s",
                self.consolidation_provider.provider_name,
                self.consolidation_provider.model_name,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Consolidation provider failed",
            ) from exc

        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Consolidation refused: provider detected contradictions or "
                    "could not safely consolidate these memories"
                ),
            )

        # Validate confidence threshold
        from app.config import get_settings
        settings = get_settings()
        if proposal.confidence < settings.consolidation_min_confidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Consolidation confidence {proposal.confidence:.2f} below "
                    f"minimum {settings.consolidation_min_confidence}"
                ),
            )

        return proposal

    def _find_semantic_duplicate(
        self,
        proposal: ConsolidationProposal,
        *,
        namespace: str,
    ) -> Memory | None:
        """
        Check if a semantically equivalent consolidated memory already exists.

        Compares the proposal embedding against embeddings of existing
        consolidated memories in the same namespace.
        Threshold: 0.92 (stricter than M5 redundancy suppression).
        """
        try:
            proposal_vec = self.embedding_provider.embed_text(proposal.content)
        except Exception:
            return None  # Can't compare — allow creation

        # Find existing consolidated memories (marked via metadata_)
        from sqlalchemy import select
        stmt = (
            select(Memory)
            .where(Memory.namespace == namespace)
            .where(Memory.status == MemoryStatus.active)
        )
        candidates = list(self.db.scalars(stmt).all())

        for mem in candidates:
            if not mem.metadata_.get("is_consolidated"):
                continue
            emb_row = self.embedding_repo.get_by_memory_id(mem.id)
            if emb_row is None:
                continue
            stored_vec = deserialize_vector(emb_row.embedding)
            sim = cosine_similarity(proposal_vec, stored_vec)
            if sim >= 0.92:
                return mem

        return None

    def _persist_consolidation(
        self,
        proposal: ConsolidationProposal,
        *,
        namespace: str,
        user_id: str | None,
    ) -> Memory:
        """
        Atomically create:
        1. Consolidated memory (with is_consolidated marker)
        2. Embedding for the new memory
        3. MemoryConsolidation audit record
        4. MemoryConsolidationSource links

        All within one transaction. Rolls back completely on failure.
        """
        now = datetime.now(UTC)
        try:
            # 1. Create derived memory
            derived = Memory(
                namespace=namespace,
                user_id=user_id,
                content=proposal.content,
                memory_type=proposal.memory_type,
                importance=proposal.importance,
                confidence=proposal.confidence,
                status=MemoryStatus.active,
                created_at=now,
                updated_at=now,
                metadata_={"is_consolidated": True},
            )
            self.db.add(derived)
            self.db.flush()

            # 2. Embedding (flush only — part of transaction)
            self.embedding_service.embed_memory(derived, commit=False)

            # 3. Consolidation audit record
            audit = MemoryConsolidation(
                namespace=namespace,
                user_id=user_id,
                created_memory_id=derived.id,
                provider=proposal.provider,
                provider_model=proposal.provider_model,
                confidence=proposal.confidence,
                reason=proposal.reason,
                created_at=now,
            )
            self.db.add(audit)
            self.db.flush()

            # 4. Source links
            for source_id in proposal.source_memory_ids:
                link = MemoryConsolidationSource(
                    consolidation_id=audit.id,
                    source_memory_id=source_id,
                )
                self.db.add(link)

            self.db.commit()
            self.db.refresh(derived)
            return derived

        except Exception:
            self.db.rollback()
            raise

    def _consolidation_to_read(self, record: MemoryConsolidation) -> ConsolidationRead:
        sources = self.consolidation_repo.list_sources_for_consolidation(record.id)
        source_reads: list[SourceMemoryRead] = []
        for s in sources:
            mem = self.memory_repo.get_by_id(s.source_memory_id)
            if mem:
                source_reads.append(
                    SourceMemoryRead(
                        memory_id=mem.id,
                        content=mem.content,
                        memory_type=mem.memory_type,
                    )
                )
        return ConsolidationRead(
            consolidation_id=record.id,
            created_memory_id=record.created_memory_id,
            namespace=record.namespace,
            user_id=record.user_id,
            provider=record.provider,
            provider_model=record.provider_model,
            confidence=record.confidence,
            reason=record.reason,
            created_at=record.created_at,
            sources=source_reads,
        )
