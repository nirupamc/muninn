"""Event ORM model — something that happened (not durable knowledge)."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class EventRole(str, enum.Enum):
    """Role associated with an event."""

    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"
    other = "other"


class Event(Base):
    """An event represents something that happened in a session."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_namespace", "namespace"),
        Index("ix_events_namespace_session", "namespace", "session_id"),
        Index("ix_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[EventRole] = mapped_column(
        Enum(EventRole, name="event_role", native_enum=False),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id!r} namespace={self.namespace!r} role={self.role!r}>"
