"""Temporal decision audit ORM model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryTemporalDecision(Base):
    """Audit record for a temporal relationship decision on an M3-NEW candidate."""

    __tablename__ = "memory_temporal_decisions"
    __table_args__ = (
        Index("ix_memory_temporal_decisions_event_id", "event_id"),
        Index("ix_memory_temporal_decisions_admission_id", "admission_id"),
        Index("ix_memory_temporal_decisions_matched_memory_id", "matched_memory_id"),
        Index("ix_memory_temporal_decisions_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    admission_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memory_admissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    dedup_decision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memory_deduplication_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_content: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    matched_memory_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_memory_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    relationship_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_valid_until_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    old_valid_until_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    new_valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryTemporalDecision event_id={self.event_id!r} "
            f"relationship={self.relationship!r}>"
        )
