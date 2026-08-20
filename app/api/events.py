"""Event HTTP endpoints."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.admission.base import AdmissionProvider
from app.admission.factory import get_admission_provider
from app.admission.service import AdmissionService
from app.database import get_db
from app.deduplication.base import RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.models.event import EventRole
from app.schemas.admission import (
    AdmissionRecordRead,
    AdmitEventResponse,
    DeduplicationRecordRead,
    MemoryHistoryResponse,
    TemporalRecordRead,
)
from app.schemas.event import EventCreate, EventRead
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])


def _to_read(event) -> EventRead:
    return EventRead.model_validate(event)


def get_admission_service(
    db: Session = Depends(get_db),
    admission_provider: AdmissionProvider = Depends(get_admission_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    relationship_provider: RelationshipProvider = Depends(get_relationship_provider),
) -> AdmissionService:
    return AdmissionService(
        db,
        admission_provider=admission_provider,
        embedding_provider=embedding_provider,
        relationship_provider=relationship_provider,
    )


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Session = Depends(get_db)) -> EventRead:
    event = EventService(db).create(payload)
    return _to_read(event)


@router.get("", response_model=list[EventRead])
def list_events(
    namespace: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    role: EventRole | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[EventRead]:
    events = EventService(db).list(
        namespace=namespace,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        role=role,
        limit=limit,
        offset=offset,
    )
    return [_to_read(event) for event in events]


@router.post("/{event_id}/admit", response_model=AdmitEventResponse)
def admit_event(
    event_id: str,
    service: AdmissionService = Depends(get_admission_service),
) -> AdmitEventResponse:
    return service.admit_event(event_id)


@router.get("/{event_id}/admissions", response_model=list[AdmissionRecordRead])
def list_event_admissions(
    event_id: str,
    service: AdmissionService = Depends(get_admission_service),
) -> list[AdmissionRecordRead]:
    rows = service.list_admissions(event_id)
    return [AdmissionRecordRead.model_validate(row) for row in rows]


@router.get("/{event_id}/deduplication", response_model=list[DeduplicationRecordRead])
def list_event_deduplication(
    event_id: str,
    service: AdmissionService = Depends(get_admission_service),
) -> list[DeduplicationRecordRead]:
    rows = service.list_deduplication(event_id)
    return [DeduplicationRecordRead.model_validate(row) for row in rows]


@router.get("/{event_id}/temporal", response_model=list[TemporalRecordRead])
def list_event_temporal(
    event_id: str,
    service: AdmissionService = Depends(get_admission_service),
) -> list[TemporalRecordRead]:
    rows = service.list_temporal(event_id)
    return [TemporalRecordRead.model_validate(row) for row in rows]


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: str, db: Session = Depends(get_db)) -> EventRead:
    event = EventService(db).get(event_id)
    return _to_read(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: str, db: Session = Depends(get_db)) -> Response:
    EventService(db).delete(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
