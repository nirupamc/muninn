"""Project service for business logic."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.project import Project, ProjectStatus
from app.projects.repository import ProjectRepository


class ProjectService:
    """Business logic for project management."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ProjectRepository(db)
        self.settings = get_settings()

    def _derive_namespace(self, name: str) -> str:
        """Derive a namespace from a project name."""
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        slug = slug.strip("-")
        return f"project:{slug}"

    def _resolve_namespace_collision(self, base_namespace: str) -> str:
        """Resolve namespace collisions by adding a numeric suffix."""
        namespace = base_namespace
        counter = 1
        while self.repo.get_by_namespace(namespace):
            counter += 1
            namespace = f"{base_namespace}-{counter}"
        return namespace

    def _canonicalize_path(self, path: str) -> str:
        """Canonicalize a path for consistent comparison."""
        return str(Path(path).resolve())

    def _find_git_root(self, path: str) -> str | None:
        """Find the Git root directory for a path."""
        from pathlib import Path
        p = Path(path).resolve()
        while p != p.parent:
            if (p / ".git").exists():
                return str(p)
            p = p.parent
        return None

    def _get_git_info(self, git_root: str) -> tuple[str | None, str | None]:
        """Get Git remote URL and default branch."""
        import subprocess
        remote_url = None
        default_branch = None
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                remote_url = result.stdout.strip()
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                default_branch = result.stdout.strip()
        except Exception:
            pass
        return remote_url, default_branch

    def register_project(
        self,
        path: str,
        *,
        name: str | None = None,
        enable_capture: bool = False,
    ) -> Project:
        """Register a project at the given path."""
        canonical_path = self._canonicalize_path(path)

        existing = self.repo.get_by_canonical_path(canonical_path)
        if existing:
            if enable_capture and not existing.capture_enabled:
                self.repo.update_capture_enabled(existing.id, True)
                self.repo.update_status(existing.id, ProjectStatus.connected)
            return existing

        project_name = name or Path(canonical_path).name
        base_namespace = self._derive_namespace(project_name)
        namespace = self._resolve_namespace_collision(base_namespace)

        git_root = self._find_git_root(path)
        remote_url = None
        default_branch = None
        if git_root:
            remote_url, default_branch = self._get_git_info(git_root)

        status = ProjectStatus.connected if enable_capture else ProjectStatus.discovered

        project = self.repo.create(
            name=project_name,
            namespace=namespace,
            root_path=path,
            canonical_path=canonical_path,
            git_root=git_root,
            remote_url=remote_url,
            default_branch=default_branch,
            status=status,
            capture_enabled=enable_capture,
        )

        return project

    def scan_workspace_roots(self) -> list[Project]:
        """Scan configured workspace roots for Git repositories."""
        from app.projects.discovery import ProjectDiscoveryService

        discovery = ProjectDiscoveryService(self.db)
        roots = self._get_workspace_roots()
        discovered = discovery.discover_projects(roots)

        newly_discovered = []
        for project in discovered:
            existing = self.repo.get_by_canonical_path(project.canonical_path)
            if not existing:
                self.repo.create(
                    name=project.name,
                    namespace=project.namespace,
                    root_path=project.root_path,
                    canonical_path=project.canonical_path,
                    git_root=project.git_root,
                    remote_url=project.remote_url,
                    default_branch=project.default_branch,
                    status=ProjectStatus.discovered,
                    capture_enabled=False,
                )
                newly_discovered.append(project)

        return newly_discovered

    def _get_workspace_roots(self) -> list[str]:
        """Get configured workspace roots from settings."""
        if not self.settings.workspace_roots:
            return []
        return [root.strip() for root in self.settings.workspace_roots.split(";") if root.strip()]

    def list_projects(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Project]:
        """List projects with optional filters."""
        return self.repo.list_all(
            status=status,
            capture_enabled=capture_enabled,
            limit=limit,
            offset=offset,
        )

    def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        return self.repo.get_by_id(project_id)

    def get_project_by_namespace(self, namespace: str) -> Project | None:
        """Get a project by namespace."""
        return self.repo.get_by_namespace(namespace)

    def enable_capture(self, project_id: str) -> Project | None:
        """Enable capture for a project."""
        project = self.repo.update_capture_enabled(project_id, True)
        if project:
            project.status = ProjectStatus.connected
            self.db.flush()
        return project

    def disable_capture(self, project_id: str) -> Project | None:
        """Disable capture for a project."""
        project = self.repo.update_capture_enabled(project_id, False)
        if project:
            project.status = ProjectStatus.disabled
            self.db.flush()
        return project

    def update_activity(self, project_id: str, occurred_at: datetime | None = None) -> Project | None:
        """Update project last activity and potentially status."""
        project = self.repo.update_last_activity(project_id, occurred_at)
        if project and project.capture_enabled and project.status == ProjectStatus.connected:
            project.status = ProjectStatus.active
            self.db.flush()
        return project

    def mark_memorized(self, project_id: str) -> Project | None:
        """Mark a project as having at least one durable memory."""
        project = self.repo.get_by_id(project_id)
        if project and project.status in (ProjectStatus.discovered, ProjectStatus.connected):
            project.status = ProjectStatus.memorized
            self.db.flush()
        return project