"""Project service for business logic."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.memory import Memory
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
        """Resolve namespace collisions by adding a numeric suffix (persisted)."""
        namespace = base_namespace
        counter = 1
        while self.repo.get_by_namespace(namespace):
            counter += 1
            namespace = f"{base_namespace}-{counter}"
        return namespace

    def _find_git_root(self, path: str) -> str | None:
        """Find the Git root directory for a path."""
        p = Path(path).resolve()
        while p != p.parent:
            if (p / ".git").exists():
                return str(p)
            p = p.parent
        return None

    def _get_git_info(self, git_root: str) -> tuple[str | None, str | None]:
        from app.projects.scanner import get_git_info

        return get_git_info(git_root)

    def register_project(
        self,
        path: str,
        *,
        name: str | None = None,
        enable_capture: bool = False,
        discovery_source: str | None = "manual",
        discovery_evidence: list[str] | None = None,
        git_root: str | None = None,
        remote_url: str | None = None,
        default_branch: str | None = None,
    ) -> Project | None:
        """Register a project at the given path (canonical-path identity)."""
        from app.projects.paths import true_case_path

        if not Path(path).exists():
            return None
        canonical_path = true_case_path(path)

        existing = self.repo.get_by_canonical_path(canonical_path)
        if existing:
            if enable_capture and not existing.capture_enabled:
                self.repo.update_capture_enabled(existing.id, True)
                self.repo.update_status(existing.id, ProjectStatus.connected)
            return existing

        project_name = name or Path(canonical_path).name
        base_namespace = self._derive_namespace(project_name)
        namespace = self._resolve_namespace_collision(base_namespace)

        if not git_root:
            git_root = self._find_git_root(path)
        if git_root and remote_url is None and default_branch is None:
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
            discovery_source=discovery_source,
            discovery_evidence=discovery_evidence or [],
        )

        return project

    # ------------------------------------------------------------------ #
    # Scans                                                               #
    # ------------------------------------------------------------------ #
    def scan_workspace_roots(self) -> list[Project]:
        """Scan configured workspace roots only; return newly registered projects.

        Legacy M8 entry point — no automatic drive expansion.
        """
        from app.projects.discovery import ProjectDiscoveryService as Orchestrator

        orchestrator = Orchestrator(self.db, settings=self.settings)
        outcome = orchestrator.run_scan(
            roots=self._get_workspace_roots(),
            include_auto_drives=False,
            persist_report=False,
        )
        return outcome.projects_new

    def run_workstation_scan(
        self,
        *,
        roots: list[str] | None = None,
        include_auto_drives: bool = True,
    ):
        """Full bounded workstation scan (priority roots + eligible drives)."""
        from app.projects.discovery import ProjectDiscoveryService as Orchestrator

        orchestrator = Orchestrator(self.db, settings=self.settings)
        return orchestrator.run_scan(roots=roots, include_auto_drives=include_auto_drives)

    def _get_workspace_roots(self) -> list[str]:
        """Get configured workspace roots from settings."""
        if not self.settings.workspace_roots:
            return []
        return [root.strip() for root in self.settings.workspace_roots.split(";") if root.strip()]

    # ------------------------------------------------------------------ #
    # Listing with memory counts                                          #
    # ------------------------------------------------------------------ #
    def memory_counts_by_namespace(self) -> dict[str, int]:
        """Count memories grouped by namespace (single aggregate query)."""
        stmt = select(Memory.namespace, func.count(Memory.id)).group_by(Memory.namespace)
        rows = self.db.execute(stmt).all()
        return {namespace: count for namespace, count in rows}

    def capture_counts_by_project(self) -> dict[str, dict[str, int]]:
        """Count capture events by project grouped by processing status and admission decision."""
        from app.models.capture import CaptureEvent, CaptureProcessingStatus, AdmissionDecision
        from sqlalchemy import case, func
        
        # Count by project, processing_status, and admission_decision
        stmt = select(
            CaptureEvent.project_id,
            CaptureEvent.processing_status,
            CaptureEvent.admission_decision,
            func.count(CaptureEvent.id)
        ).group_by(CaptureEvent.project_id, CaptureEvent.processing_status, CaptureEvent.admission_decision)
        
        rows = self.db.execute(stmt).all()
        result: dict[str, dict[str, int]] = {}
        for project_id, status, decision, count in rows:
            if project_id not in result:
                result[project_id] = {}
            
            status_key = status.value if hasattr(status, 'value') else str(status)
            
            # For completed events, distinguish between STORE and IGNORE
            if status_key == "completed":
                if decision and hasattr(decision, 'value'):
                    decision_key = decision.value
                    result[project_id][f"{status_key}_{decision_key}"] = result[project_id].get(f"{status_key}_{decision_key}", 0) + count
                else:
                    result[project_id][status_key] = result[project_id].get(status_key, 0) + count
            else:
                result[project_id][status_key] = result[project_id].get(status_key, 0) + count
        return result

    def get_last_capture_timestamps(self) -> dict[str, datetime | None]:
        """Get last capture timestamp by project_id."""
        from app.models.capture import CaptureEvent
        from sqlalchemy import func
        
        stmt = select(
            CaptureEvent.project_id,
            func.max(CaptureEvent.occurred_at)
        ).group_by(CaptureEvent.project_id)
        
        rows = self.db.execute(stmt).all()
        return {project_id: timestamp for project_id, timestamp in rows}

    def list_projects_with_full_counts(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        include_ignored: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[Sequence[Project], dict[str, int], dict[str, dict[str, int]], dict[str, datetime | None], int]:
        """Projects plus per-namespace memory counts, capture counts, timestamps, and filtered total."""
        projects = self.repo.list_all(
            status=status,
            capture_enabled=capture_enabled,
            include_ignored=include_ignored,
            limit=limit,
            offset=offset,
        )
        memory_counts = self.memory_counts_by_namespace()
        capture_counts = self.capture_counts_by_project()
        last_capture_timestamps = self.get_last_capture_timestamps()
        total = self.repo.count(status=status, include_ignored=include_ignored)
        return projects, memory_counts, capture_counts, last_capture_timestamps, total

    def list_projects_with_counts(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        include_ignored: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[Sequence[Project], dict[str, int], int]:
        """Projects plus per-namespace memory counts and filtered total."""
        projects = self.repo.list_all(
            status=status,
            capture_enabled=capture_enabled,
            include_ignored=include_ignored,
            limit=limit,
            offset=offset,
        )
        counts = self.memory_counts_by_namespace()
        total = self.repo.count(status=status, include_ignored=include_ignored)
        return projects, counts, total

    def list_projects(
        self,
        *,
        status: ProjectStatus | None = None,
        capture_enabled: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Project]:
        """List projects with optional filters (ignores ignored by default)."""
        return self.repo.list_all(status=status, capture_enabled=capture_enabled, limit=limit, offset=offset)

    def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        return self.repo.get_by_id(project_id)

    def find_project(self, id_or_namespace: str) -> Project | None:
        """Resolve a project by ID or namespace (CLI convenience)."""
        project = self.repo.get_by_id(id_or_namespace)
        if project is None:
            project = self.repo.get_by_namespace(id_or_namespace)
        return project

    def get_project_by_namespace(self, namespace: str) -> Project | None:
        """Get a project by namespace."""
        return self.repo.get_by_namespace(namespace)

    def set_ignored(self, project_id: str, ignored: bool) -> Project | None:
        """Ignore/unignore — ignored projects stay out of scans and default lists."""
        return self.repo.set_ignored(project_id, ignored)

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
