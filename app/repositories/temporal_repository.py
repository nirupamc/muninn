"""Temporal decision audit persistence."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.temporal import MemoryTemporalDecision


class TemporalRepository:
    """Data-access layer for temporal decision audits."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_event_id(self, event_id: str) -> list[MemoryTemporalDecision]:
        stmt = (
            select(MemoryTemporalDecision)
            .where(MemoryTemporalDecision.event_id == event_id)
            .order_by(
                MemoryTemporalDecision.created_at.asc(),
                MemoryTemporalDecision.id.asc(),
            )
        )
        return list(self.db.scalars(stmt).all())

    def list_for_memory(self, memory_id: str) -> list[MemoryTemporalDecision]:
        """History rows where this memory was matched or created."""
        stmt = (
            select(MemoryTemporalDecision)
            .where(
                or_(
                    MemoryTemporalDecision.matched_memory_id == memory_id,
                    MemoryTemporalDecision.created_memory_id == memory_id,
                )
            )
            .order_by(
                MemoryTemporalDecision.created_at.asc(),
                MemoryTemporalDecision.id.asc(),
            )
        )
        return list(self.db.scalars(stmt).all())

    def create(
        self,
        row: MemoryTemporalDecision,
        *,
        commit: bool = False,
    ) -> MemoryTemporalDecision:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row
