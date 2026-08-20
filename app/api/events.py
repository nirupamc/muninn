"""Event HTTP endpoints."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.event import EventRole
from app.schemas.event import EventCreate, EventRead
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"])


def _to_read(event) -> EventRead:
    return EventRead.model_validate(event)


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


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: str, db: Session = Depends(get_db)) -> EventRead:
    event = EventService(db).get(event_id)
    return _to_read(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: str, db: Session = Depends(get_db)) -> Response:
    EventService(db).delete(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
