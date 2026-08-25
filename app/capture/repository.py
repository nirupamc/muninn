"""CaptureEvent repository for data access."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capture import (
    CaptureEvent,
    CaptureEventType,
    CaptureProcessingStatus,
    CaptureSource,
    AdmissionDecision,
)


class CaptureEventRepository:
    """Data access layer for capture events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        project_id: str,
        namespace: str,
        source: CaptureSource,
        source_event_type: CaptureEventType,
        agent_id: str | None = None,
        session_id: str | None = None,
        working_directory: str | None = None,
        content: str,
        metadata: dict[str, Any] | None = None,
        fingerprint: str,
        occurred_at: datetime,
        processing_status: CaptureProcessingStatus = CaptureProcessingStatus.pending,
    ) -> CaptureEvent:
        """Create a new capture event."""
        event = CaptureEvent(
            project_id=project_id,
            namespace=namespace,
            source=source,
            source_event_type=source_event_type,
            agent_id=agent_id,
            session_id=session_id,
            working_directory=working_directory,
            content=content,
            metadata_=metadata or {},
            fingerprint=fingerprint,
            occurred_at=occurred_at,
            processing_status=processing_status,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def get_by_id(self, event_id: str) -> CaptureEvent | None:
        """Get capture event by ID."""
        return self.db.get(CaptureEvent, event_id)

    def get_by_fingerprint(self, fingerprint: str) -> CaptureEvent | None:
        """Get capture event by fingerprint."""
        stmt = select(CaptureEvent).where(CaptureEvent.fingerprint == fingerprint)
        return self.db.execute(stmt).scalar_one_or_none()

    def exists_by_fingerprint(self, fingerprint: str) -> bool:
        """Check if a capture event with the given fingerprint exists."""
        return self.get_by_fingerprint(fingerprint) is not None

    def list_by_project(
        self,
        project_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        status: CaptureProcessingStatus | None = None,
        source: CaptureSource | None = None,
    ) -> Sequence[CaptureEvent]:
        """List capture events for a project."""
        stmt = (
            select(CaptureEvent)
            .where(CaptureEvent.project_id == project_id)
            .order_by(CaptureEvent.occurred_at.desc())
        )
        if status is not None:
            stmt = stmt.where(CaptureEvent.processing_status == status)
        if source is not None:
            stmt = stmt.where(CaptureEvent.source == source)
        stmt = stmt.limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def list_recent(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        since: datetime | None = None,
    ) -> Sequence[CaptureEvent]:
        """List recent capture events across all projects."""
        stmt = select(CaptureEvent).order_by(CaptureEvent.captured_at.desc())
        if since is not None:
            stmt = stmt.where(CaptureEvent.captured_at >= since)
        stmt = stmt.limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def update_status(
        self,
        event_id: str,
        status: CaptureProcessingStatus,
        *,
        memory_event_id: str | None = None,
        memory_id: str | None = None,
        admission_decision: AdmissionDecision | None = None,
        error: str | None = None,
    ) -> CaptureEvent | None:
        """Update capture event processing status."""
        event = self.get_by_id(event_id)
        if event:
            event.processing_status = status
            if memory_event_id is not None:
                event.memory_event_id = memory_event_id
            if memory_id is not None:
                event.memory_id = memory_id
            if admission_decision is not None:
                event.admission_decision = admission_decision
            if error is not None:
                event.error = error
            self.db.flush()
        return event

    def count_by_project(
        self,
        project_id: str,
        *,
        status: CaptureProcessingStatus | None = None,
    ) -> int:
        """Count capture events for a project."""
        stmt = select(CaptureEvent).where(CaptureEvent.project_id == project_id)
        if status is not None:
            stmt = stmt.where(CaptureEvent.processing_status == status)
        return len(self.db.execute(stmt).scalars().all())