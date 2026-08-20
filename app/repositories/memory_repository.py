"""Memory persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memory import Memory, MemoryStatus, MemoryType


class MemoryRepository:
    """Data-access layer for memories."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, memory: Memory, *, commit: bool = True) -> Memory:
        self.db.add(memory)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(memory)
        return memory

    def get_by_id(self, memory_id: str) -> Memory | None:
        return self.db.get(Memory, memory_id)

    def list(
        self,
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        stmt = select(Memory)
        if namespace is not None:
            stmt = stmt.where(Memory.namespace == namespace)
        if user_id is not None:
            stmt = stmt.where(Memory.user_id == user_id)
        if agent_id is not None:
            stmt = stmt.where(Memory.agent_id == agent_id)
        if memory_type is not None:
            stmt = stmt.where(Memory.memory_type == memory_type)
        if status is not None:
            stmt = stmt.where(Memory.status == status)

        stmt = stmt.order_by(Memory.created_at.desc(), Memory.id.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def update(self, memory: Memory, updates: dict, *, commit: bool = True) -> Memory:
        for key, value in updates.items():
            setattr(memory, key, value)
        # Ensure updated_at advances even on SQLite without reliable onupdate triggers.
        memory.updated_at = datetime.now(UTC)
        self.db.add(memory)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(memory)
        return memory

    def delete(self, memory: Memory, *, commit: bool = True) -> None:
        self.db.delete(memory)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
