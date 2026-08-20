"""Event application service."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.event import Event, EventRole
from app.repositories.event_repository import EventRepository
from app.schemas.event import EventCreate


class EventService:
    """Thin service layer for event operations."""

    def __init__(self, db: Session) -> None:
        self.repo = EventRepository(db)

    def create(self, payload: EventCreate) -> Event:
        event = Event(
            namespace=payload.namespace,
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            session_id=payload.session_id,
            role=payload.role,
            content=payload.content,
            metadata_=payload.metadata,
        )
        return self.repo.create(event)

    def get(self, event_id: str) -> Event:
        event = self.repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event '{event_id}' not found",
            )
        return event

    def list(
        self,
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        role: EventRole | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        return self.repo.list(
            namespace=namespace,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            role=role,
            limit=limit,
            offset=offset,
        )

    def delete(self, event_id: str) -> None:
        event = self.get(event_id)
        self.repo.delete(event)
