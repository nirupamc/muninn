"""Consolidation audit ORM models.

MemoryConsolidation — one row per consolidation operation.
MemoryConsolidationSource — many-to-many: consolidation → source memories.

Source memories are NEVER deleted by consolidation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryConsolidation(Base):
    """Audit record for a consolidation operation."""

    __tablename__ = "memory_consolidations"
    __table_args__ = (
        Index("ix_memory_consolidations_namespace", "namespace"),
        Index("ix_memory_consolidations_created_memory_id", "created_memory_id"),
        Index("ix_memory_consolidations_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_memory_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryConsolidation id={self.id!r} "
            f"created_memory_id={self.created_memory_id!r}>"
        )


class MemoryConsolidationSource(Base):
    """Source memory link for a consolidation operation."""

    __tablename__ = "memory_consolidation_sources"
    __table_args__ = (
        Index(
            "ix_memory_consolidation_sources_consolidation_id",
            "consolidation_id",
        ),
        Index(
            "ix_memory_consolidation_sources_source_memory_id",
            "source_memory_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    consolidation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("memory_consolidations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_memory_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryConsolidationSource "
            f"consolidation_id={self.consolidation_id!r} "
            f"source_memory_id={self.source_memory_id!r}>"
        )
