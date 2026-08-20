"""Memory ORM model — durable knowledge extracted or stored for agents."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryType(str, enum.Enum):
    """Classification of durable memory content."""

    fact = "fact"
    preference = "preference"
    project = "project"
    goal = "goal"
    decision = "decision"
    event = "event"
    relationship = "relationship"
    procedure = "procedure"
    other = "other"


class MemoryStatus(str, enum.Enum):
    """Lifecycle status of a memory."""

    active = "active"
    superseded = "superseded"
    invalidated = "invalidated"
    archived = "archived"


class Memory(Base):
    """A memory represents durable knowledge."""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_namespace", "namespace"),
        Index("ix_memories_namespace_status", "namespace", "status"),
        Index("ix_memories_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[MemoryType] = mapped_column(
        Enum(MemoryType, name="memory_type", native_enum=False),
        nullable=False,
    )
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[MemoryStatus] = mapped_column(
        Enum(MemoryStatus, name="memory_status", native_enum=False),
        nullable=False,
        default=MemoryStatus.active,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return (
            f"<Memory id={self.id!r} namespace={self.namespace!r} "
            f"type={self.memory_type!r} status={self.status!r}>"
        )
