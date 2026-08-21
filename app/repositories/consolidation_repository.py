"""Consolidation persistence operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consolidation import MemoryConsolidation, MemoryConsolidationSource


class ConsolidationRepository:
    """Data-access layer for consolidation audit and provenance."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_consolidation(
        self,
        row: MemoryConsolidation,
        *,
        commit: bool = False,
    ) -> MemoryConsolidation:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row

    def create_source(
        self,
        row: MemoryConsolidationSource,
        *,
        commit: bool = False,
    ) -> MemoryConsolidationSource:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row

    def get_consolidation_by_id(self, consolidation_id: str) -> MemoryConsolidation | None:
        return self.db.get(MemoryConsolidation, consolidation_id)

    def get_consolidation_by_memory_id(
        self, memory_id: str
    ) -> MemoryConsolidation | None:
        """Return the consolidation record that created this memory, if any."""
        stmt = select(MemoryConsolidation).where(
            MemoryConsolidation.created_memory_id == memory_id
        )
        return self.db.scalars(stmt).first()

    def list_consolidations_for_source(
        self, source_memory_id: str
    ) -> list[MemoryConsolidation]:
        """Return all consolidations that used this memory as a source."""
        stmt = (
            select(MemoryConsolidation)
            .join(
                MemoryConsolidationSource,
                MemoryConsolidationSource.consolidation_id == MemoryConsolidation.id,
            )
            .where(MemoryConsolidationSource.source_memory_id == source_memory_id)
            .order_by(MemoryConsolidation.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    def list_sources_for_consolidation(
        self, consolidation_id: str
    ) -> list[MemoryConsolidationSource]:
        stmt = (
            select(MemoryConsolidationSource)
            .where(MemoryConsolidationSource.consolidation_id == consolidation_id)
            .order_by(MemoryConsolidationSource.id.asc())
        )
        return list(self.db.scalars(stmt).all())

    def find_equivalent_consolidation(
        self,
        *,
        namespace: str,
        source_memory_ids: list[str],
    ) -> MemoryConsolidation | None:
        """
        Return an existing consolidation whose source set exactly matches.

        Used for idempotency: prevent duplicate consolidated memories for
        the identical source set.
        """
        if not source_memory_ids:
            return None

        sorted_ids = sorted(source_memory_ids)
        n = len(sorted_ids)

        # Find all consolidations in this namespace that have exactly n sources
        # and all n source IDs match
        stmt = (
            select(MemoryConsolidation)
            .where(MemoryConsolidation.namespace == namespace)
            .order_by(MemoryConsolidation.created_at.desc())
        )
        candidates = list(self.db.scalars(stmt).all())

        for candidate in candidates:
            sources = self.list_sources_for_consolidation(candidate.id)
            existing_ids = sorted(s.source_memory_id for s in sources)
            if existing_ids == sorted_ids:
                return candidate

        return None
