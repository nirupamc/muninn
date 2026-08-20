"""Deduplication audit and reinforcement persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.deduplication import MemoryDeduplicationDecision, MemoryReinforcement


class DeduplicationRepository:
    """Data-access layer for dedup audits and reinforcements."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_decisions_by_event_id(self, event_id: str) -> list[MemoryDeduplicationDecision]:
        stmt = (
            select(MemoryDeduplicationDecision)
            .where(MemoryDeduplicationDecision.event_id == event_id)
            .order_by(
                MemoryDeduplicationDecision.created_at.asc(),
                MemoryDeduplicationDecision.id.asc(),
            )
        )
        return list(self.db.scalars(stmt).all())

    def list_reinforcements_by_memory_id(self, memory_id: str) -> list[MemoryReinforcement]:
        stmt = (
            select(MemoryReinforcement)
            .where(MemoryReinforcement.memory_id == memory_id)
            .order_by(MemoryReinforcement.created_at.asc(), MemoryReinforcement.id.asc())
        )
        return list(self.db.scalars(stmt).all())

    def create_decision(
        self,
        row: MemoryDeduplicationDecision,
        *,
        commit: bool = False,
    ) -> MemoryDeduplicationDecision:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row

    def create_reinforcement(
        self,
        row: MemoryReinforcement,
        *,
        commit: bool = False,
    ) -> MemoryReinforcement:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row
