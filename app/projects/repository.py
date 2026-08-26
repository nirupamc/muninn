"""Project repository for data access."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStatus
from app.projects.paths import canonical_key


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
        discovery_source: str | None = None,
        discovery_evidence: list[Any] | None = None,
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
            discovery_source=discovery_source,
            discovery_evidence_json=discovery_evidence or [],
            last_discovered_at=datetime.now(UTC),
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
        """Get project by canonical path (case/separator-insensitive on Windows)."""
        key = canonical_key(canonical_path)
        stmt = select(Project).where(func.lower(Project.canonical_path) == key)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_ignored_path_keys(self) -> set[str]:
        """Canonical keys of ignored projects — pruned from scans."""
        stmt = select(Project.canonical_path).where(Project.ignored.is_(True))
        return {canonical_key(p) for p in self.db.execute(stmt).scalars().all()}

    def set_ignored(self, project_id: str, ignored: bool) -> Project | None:
        """Persistently ignore/unignore a project (never auto re-added)."""
        project = self.get_by_id(project_id)
        if project:
            project.ignored = ignored
            self.db.flush()
        return project

    def list_all(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        include_ignored: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Project]:
        """List projects with optional filters."""
        stmt = select(Project).order_by(Project.name.asc())
        if not include_ignored:
            stmt = stmt.where(Project.ignored.is_(False))
        if status is not None:
            stmt = stmt.where(Project.status == status)
        if capture_enabled is not None:
            stmt = stmt.where(Project.capture_enabled == capture_enabled)
        stmt = stmt.limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def count(self, *, status: ProjectStatus | None = None, include_ignored: bool = True) -> int:
        """Count projects with optional filter."""
        stmt = select(Project)
        if not include_ignored:
            stmt = stmt.where(Project.ignored.is_(False))
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

    def touch_discovered(self, project_id: str, occurred_at: datetime | None = None) -> Project | None:
        """Record that a rescan re-observed this project."""
        project = self.get_by_id(project_id)
        if project:
            project.last_discovered_at = occurred_at or datetime.now(UTC)
            self.db.flush()
        return project

    def update_metadata(self, project_id: str, metadata: dict[str, Any]) -> Project | None:
        """Merge keys into project metadata."""
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
