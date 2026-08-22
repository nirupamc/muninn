"""Event persistence operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import Event, EventRole


class EventRepository:
    """Data-access layer for events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, event: Event) -> Event:
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_by_id(self, event_id: str) -> Event | None:
        return self.db.get(Event, event_id)

    def find_by_idempotency_key(
        self,
        *,
        namespace: str,
        user_id: str | None,
        agent_id: str | None,
        key: str,
    ) -> Event | None:
        """Return an existing event carrying the given idempotency key.

        Scoped by namespace / user / agent so retries within the same scope
        replay the original admission instead of creating a duplicate event.
        """
        stmt = select(Event).where(
            Event.namespace == namespace,
            Event.metadata_["idempotency_key"].as_string() == key,
        )
        if user_id is not None:
            stmt = stmt.where(Event.user_id == user_id)
        if agent_id is not None:
            stmt = stmt.where(Event.agent_id == agent_id)
        return self.db.scalars(stmt).first()

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
        stmt = select(Event)
        if namespace is not None:
            stmt = stmt.where(Event.namespace == namespace)
        if user_id is not None:
            stmt = stmt.where(Event.user_id == user_id)
        if agent_id is not None:
            stmt = stmt.where(Event.agent_id == agent_id)
        if session_id is not None:
            stmt = stmt.where(Event.session_id == session_id)
        if role is not None:
            stmt = stmt.where(Event.role == role)

        stmt = stmt.order_by(Event.created_at.desc(), Event.id.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def delete(self, event: Event) -> None:
        self.db.delete(event)
        self.db.commit()
