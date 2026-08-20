"""Admission audit persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admission import MemoryAdmission


class AdmissionRepository:
    """Data-access layer for memory admission audits."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_event_id(self, event_id: str) -> list[MemoryAdmission]:
        stmt = (
            select(MemoryAdmission)
            .where(MemoryAdmission.event_id == event_id)
            .order_by(MemoryAdmission.created_at.asc(), MemoryAdmission.id.asc())
        )
        return list(self.db.scalars(stmt).all())

    def has_admissions(self, event_id: str) -> bool:
        return len(self.list_by_event_id(event_id)) > 0

    def create(self, row: MemoryAdmission, *, commit: bool = False) -> MemoryAdmission:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(row)
        return row

    def create_many(
        self,
        rows: list[MemoryAdmission],
        *,
        commit: bool = False,
    ) -> list[MemoryAdmission]:
        for row in rows:
            self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        for row in rows:
            self.db.refresh(row)
        return rows
