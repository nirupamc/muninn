"""CaptureEvent ORM model — raw normalized activity capture audit."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CaptureSource(str, enum.Enum):
    """Source of the capture event."""

    git = "git"
    filesystem = "filesystem"
    codex = "codex"
    kilo = "kilo"
    opencode = "opencode"
    cline = "cline"
    aider = "aider"
    generic = "generic"
    manual = "manual"


class CaptureEventType(str, enum.Enum):
    """Type of capture event."""

    # Legacy types (pre-M12)
    project_discovered = "project_discovered"
    git_commit = "git_commit"
    git_branch_change = "git_branch_change"
    file_batch_changed = "file_batch_changed"
    agent_session_started = "agent_session_started"
    agent_session_finished = "agent_session_finished"
    agent_summary = "agent_summary"
    agent_decision = "agent_decision"
    agent_tool_result = "agent_tool_result"
    manual_note = "manual_note"

    # M12 — Structured observation types
    command_run = "command_run"
    command_result = "command_result"
    test_run = "test_run"
    test_result = "test_result"
    file_edit = "file_edit"
    file_create = "file_create"
    file_delete = "file_delete"
    error_event = "error_event"
    warning_event = "warning_event"
    verification = "verification"
    blocker_event = "blocker_event"
    decision_event = "decision_event"
    build_result = "build_result"
    api_result = "api_result"


class CaptureProcessingStatus(str, enum.Enum):
    """Processing status of a capture event."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AdmissionDecision(str, enum.Enum):
    """Admission decision for the capture event."""

    store = "STORE"
    ignore = "IGNORE"


class CaptureEvent(Base):
    """A normalized capture event from any activity source."""

    __tablename__ = "capture_events"
    __table_args__ = (
        Index("ix_capture_events_project_id", "project_id"),
        Index("ix_capture_events_namespace", "namespace"),
        Index("ix_capture_events_source", "source"),
        Index("ix_capture_events_fingerprint", "fingerprint", unique=True),
        Index("ix_capture_events_occurred_at", "occurred_at"),
        Index("ix_capture_events_processing_status", "processing_status"),
        Index("ix_capture_events_memory_id", "memory_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[CaptureSource] = mapped_column(
        Enum(CaptureSource, name="capture_source", native_enum=False),
        nullable=False,
    )
    source_event_type: Mapped[CaptureEventType] = mapped_column(
        Enum(CaptureEventType, name="capture_event_type", native_enum=False),
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    working_directory: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    fingerprint: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    processing_status: Mapped[CaptureProcessingStatus] = mapped_column(
        Enum(CaptureProcessingStatus, name="capture_processing_status", native_enum=False),
        nullable=False,
        default=CaptureProcessingStatus.pending,
    )
    memory_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    admission_decision: Mapped[AdmissionDecision | None] = mapped_column(
        Enum(AdmissionDecision, name="admission_decision", native_enum=False),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CaptureEvent id={self.id!r} project_id={self.project_id!r} source={self.source!r} type={self.source_event_type!r} status={self.processing_status!r}>"