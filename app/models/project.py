"""Project ORM model — a discovered workspace project."""

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


class ProjectStatus(str, enum.Enum):
    """Lifecycle status of a discovered project."""

    discovered = "DISCOVERED"
    connected = "CONNECTED"
    memorized = "MEMORIZED"
    active = "ACTIVE"
    disabled = "DISABLED"


class Project(Base):
    """A project represents a discovered workspace root with Git/repository identity."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_namespace", "namespace", unique=True),
        Index("ix_projects_canonical_path", "canonical_path", unique=True),
        Index("ix_projects_status", "status"),
        Index("ix_projects_last_activity", "last_activity_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    canonical_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    git_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", native_enum=False),
        nullable=False,
        default=ProjectStatus.discovered,
    )
    capture_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id!r} name={self.name!r} namespace={self.namespace!r} status={self.status!r}>"