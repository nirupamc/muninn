"""Capture API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.capture.adapters import create_agent_summary_event
from app.capture.project_resolver import ProjectResolver
from app.capture.repository import CaptureEventRepository
from app.capture.service import CaptureService
from app.database import get_db
from app.models.capture import (
    CaptureEvent,
    CaptureEventType,
    CaptureProcessingStatus,
    CaptureSource,
    AdmissionDecision,
)
from app.models.project import Project


router = APIRouter(prefix="/capture", tags=["capture"])


class CaptureEventRequest(BaseModel):
    project_path: str | None = None
    namespace: str | None = None
    source: CaptureSource = CaptureSource.generic
    event_type: CaptureEventType = CaptureEventType.manual_note
    agent_id: str | None = None
    session_id: str | None = None
    working_directory: str | None = None
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None


class AgentSummaryRequest(BaseModel):
    project_path: str | None = None
    namespace: str | None = None
    agent_id: str = "generic"
    session_id: str | None = None
    summary: str = Field(..., min_length=1)
    working_directory: str | None = None
    metadata: dict[str, Any] | None = None


class CaptureEventResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    project_id: str
    namespace: str
    source: str
    event_type: str
    agent_id: str | None
    session_id: str | None
    working_directory: str | None
    content: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    fingerprint: str
    occurred_at: datetime
    captured_at: datetime
    processing_status: str
    memory_event_id: str | None
    memory_id: str | None
    admission_decision: str | None
    error: str | None


class CaptureStatusResponse(BaseModel):
    projects_with_capture: int
    total_capture_events: int
    pending_events: int
    adapter_health: dict[str, list[dict[str, Any]]]


def _to_response(event: CaptureEvent) -> CaptureEventResponse:
    return CaptureEventResponse(
        id=event.id,
        project_id=event.project_id,
        namespace=event.namespace,
        source=event.source.value,
        event_type=event.source_event_type.value,
        agent_id=event.agent_id,
        session_id=event.session_id,
        working_directory=event.working_directory,
        content=event.content,
        metadata=event.metadata_,
        fingerprint=event.fingerprint,
        occurred_at=event.occurred_at,
        captured_at=event.captured_at,
        processing_status=event.processing_status.value,
        memory_event_id=event.memory_event_id,
        memory_id=event.memory_id,
        admission_decision=event.admission_decision.value if event.admission_decision else None,
        error=event.error,
    )


@router.post(
    "/events",
    response_model=CaptureEventResponse,
    summary="Submit a capture event",
)
def submit_capture_event(
    payload: CaptureEventRequest,
    db: Session = Depends(get_db),
) -> CaptureEventResponse:
    """Submit a capture event via the generic bridge."""
    resolver = ProjectResolver(db)
    service = CaptureService(db)

    project = resolver.resolve_or_create(
        path=payload.project_path,
        namespace=payload.namespace,
        auto_register=True,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found. Provide project_path or namespace, or enable auto_register.",
        )

    # Generate fingerprint if not provided
    if not payload.fingerprint:
        from app.capture.fingerprints import make_generic_fingerprint
        payload.fingerprint = make_generic_fingerprint(
            project,
            payload.source,
            payload.event_type,
            payload.content,
        )

    # Check idempotency
    repo = CaptureEventRepository(db)
    existing = repo.get_by_fingerprint(payload.fingerprint)
    if existing:
        return _to_response(existing)

    capture = service.capture_event(
        project=project,
        source=payload.source,
        source_event_type=payload.event_type,
        content=payload.content,
        agent_id=payload.agent_id,
        session_id=payload.session_id,
        working_directory=payload.working_directory,
        metadata=payload.metadata,
        fingerprint=payload.fingerprint,
    )

    return _to_response(capture)


@router.post(
    "/events/agent-summary",
    response_model=CaptureEventResponse,
    summary="Submit an agent session summary",
)
def submit_agent_summary(
    payload: AgentSummaryRequest,
    db: Session = Depends(get_db),
) -> CaptureEventResponse:
    """Submit an agent session summary via the generic bridge."""
    resolver = ProjectResolver(db)
    service = CaptureService(db)

    project = resolver.resolve_or_create(
        path=payload.project_path,
        namespace=payload.namespace,
        auto_register=True,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found. Provide project_path or namespace.",
        )

    capture = service.capture_agent_summary(
        project=project,
        summary=payload.summary,
        agent_id=payload.agent_id,
        session_id=payload.session_id,
        working_directory=payload.working_directory,
    )

    return _to_response(capture)


@router.get(
    "/events",
    response_model=list[CaptureEventResponse],
    summary="List capture events",
)
def list_capture_events(
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: CaptureProcessingStatus | None = None,
    source: CaptureSource | None = None,
    since: datetime | None = None,
    db: Session = Depends(get_db),
) -> list[CaptureEventResponse]:
    """List capture events with optional filters."""
    repo = CaptureEventRepository(db)

    if project_id:
        events = repo.list_by_project(project_id, limit=limit, offset=offset, status=status, source=source)
    else:
        events = repo.list_recent(limit=limit, offset=offset, since=since)

    return [_to_response(e) for e in events]


@router.get(
    "/events/{event_id}",
    response_model=CaptureEventResponse,
    summary="Get capture event",
)
def get_capture_event(
    event_id: str,
    db: Session = Depends(get_db),
) -> CaptureEventResponse:
    """Get a capture event by ID."""
    repo = CaptureEventRepository(db)
    event = repo.get_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Capture event not found")
    return _to_response(event)


@router.get(
    "/status",
    response_model=CaptureStatusResponse,
    summary="Get capture system status",
)
def get_capture_status(
    db: Session = Depends(get_db),
) -> CaptureStatusResponse:
    """Get capture system status."""
    from app.projects.repository import ProjectRepository
    from app.capture.manager import get_capture_manager

    project_repo = ProjectRepository(db)
    projects = project_repo.list_all(capture_enabled=True, limit=1000)

    capture_repo = CaptureEventRepository(db)
    total_events = 0
    pending_events = 0
    for p in projects:
        total_events += capture_repo.count_by_project(p.id)
        pending_events += capture_repo.count_by_project(p.id, status=CaptureProcessingStatus.pending)

    manager = get_capture_manager()
    adapter_health = {}
    if manager:
        for project in projects:
            adapter_health[project.id] = manager.get_adapter_health(project.id)

    return CaptureStatusResponse(
        projects_with_capture=len(projects),
        total_capture_events=total_events,
        pending_events=pending_events,
        adapter_health=adapter_health,
    )