"""Admission audit ORM model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryAdmission(Base):
    """Audit record for a memory admission decision."""

    __tablename__ = "memory_admissions"
    __table_args__ = (
        Index("ix_memory_admissions_event_id", "event_id"),
        Index("ix_memory_admissions_created_at", "created_at"),
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
    candidate_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    admission_score: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_utility: Mapped[float | None] = mapped_column(Float, nullable=True)
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    specificity: Mapped[float | None] = mapped_column(Float, nullable=True)
    explicitness: Mapped[float | None] = mapped_column(Float, nullable=True)
    triviality: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_memory_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
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
            f"<MemoryAdmission event_id={self.event_id!r} "
            f"decision={self.decision!r} score={self.admission_score}>"
        )
