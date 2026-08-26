"""Project resolver for mapping capture events to projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStatus
from app.projects.repository import ProjectRepository


class ProjectResolver:
    """Resolves projects from paths or namespaces for capture events."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ProjectRepository(db)

    def resolve_by_path(self, path: str) -> Project | None:
        """Resolve a project by filesystem path."""
        canonical = str(Path(path).resolve())
        return self.repo.get_by_canonical_path(canonical)

    def resolve_by_namespace(self, namespace: str) -> Project | None:
        """Resolve a project by namespace."""
        return self.repo.get_by_namespace(namespace)

    def resolve_or_create(
        self,
        *,
        path: str | None = None,
        namespace: str | None = None,
        name: str | None = None,
        auto_register: bool = True,
    ) -> Project | None:
        """Resolve or optionally create a project."""
        if path:
            project = self.resolve_by_path(path)
            if project:
                return project

        if namespace:
            project = self.resolve_by_namespace(namespace)
            if project:
                return project

        if not auto_register:
            return None

        if not path:
            return None

        # Auto-register the project
        from app.projects.service import ProjectService

        service = ProjectService(self.db)
        return service.register_project(path, name=name, enable_capture=True)

    def get_active_projects(self) -> list[Project]:
        """Get all projects with capture enabled."""
        return self.repo.list_all(capture_enabled=True, limit=1000)