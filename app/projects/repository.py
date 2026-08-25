"""Project repository for data access."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStatus


class ProjectRepository:
    """Data access layer for projects."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        name: str,
        namespace: str,
        root_path: str,
        canonical_path: str,
        git_root: str | None = None,
        remote_url: str | None = None,
        default_branch: str | None = None,
        status: ProjectStatus = ProjectStatus.discovered,
        capture_enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        """Create a new project."""
        project = Project(
            name=name,
            namespace=namespace,
            root_path=root_path,
            canonical_path=canonical_path,
            git_root=git_root,
            remote_url=remote_url,
            default_branch=default_branch,
            status=status,
            capture_enabled=capture_enabled,
            metadata_=metadata or {},
        )
        self.db.add(project)
        self.db.flush()
        return project

    def get_by_id(self, project_id: str) -> Project | None:
        """Get project by ID."""
        return self.db.get(Project, project_id)

    def get_by_namespace(self, namespace: str) -> Project | None:
        """Get project by namespace."""
        stmt = select(Project).where(Project.namespace == namespace)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_canonical_path(self, canonical_path: str) -> Project | None:
        """Get project by canonical path."""
        stmt = select(Project).where(Project.canonical_path == canonical_path)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Project]:
        """List projects with optional filters."""
        stmt = select(Project).order_by(Project.discovered_at.desc())
        if status is not None:
            stmt = stmt.where(Project.status == status)
        if capture_enabled is not None:
            stmt = stmt.where(Project.capture_enabled == capture_enabled)
        stmt = stmt.limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def count(self, *, status: ProjectStatus | None = None) -> int:
        """Count projects with optional filter."""
        stmt = select(Project)
        if status is not None:
            stmt = stmt.where(Project.status == status)
        return len(self.db.execute(stmt).scalars().all())

    def update_status(self, project_id: str, status: ProjectStatus) -> Project | None:
        """Update project status."""
        project = self.get_by_id(project_id)
        if project:
            project.status = status
            self.db.flush()
        return project

    def update_capture_enabled(self, project_id: str, enabled: bool) -> Project | None:
        """Update project capture enabled flag."""
        project = self.get_by_id(project_id)
        if project:
            project.capture_enabled = enabled
            self.db.flush()
        return project

    def update_last_activity(self, project_id: str, occurred_at: datetime | None = None) -> Project | None:
        """Update project last activity timestamp."""
        project = self.get_by_id(project_id)
        if project:
            project.last_activity_at = occurred_at or datetime.now(UTC)
            self.db.flush()
        return project

    def update_metadata(self, project_id: str, metadata: dict[str, Any]) -> Project | None:
        """Update project metadata."""
        project = self.get_by_id(project_id)
        if project:
            project.metadata_.update(metadata)
            self.db.flush()
        return project

    def delete(self, project_id: str) -> bool:
        """Delete a project."""
        project = self.get_by_id(project_id)
        if project:
            self.db.delete(project)
            self.db.flush()
            return True
        return False