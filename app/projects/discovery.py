"""Project discovery service for scanning workspace roots."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStatus
from app.projects.repository import ProjectRepository


@dataclass
class DiscoveredProject:
    """A discovered project before persistence."""

    name: str
    namespace: str
    root_path: str
    canonical_path: str
    git_root: str | None
    remote_url: str | None
    default_branch: str | None


class ProjectDiscoveryService:
    """Discovers projects from configured workspace roots."""

    EXCLUDED_DIRS = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "__pycache__",
        "AppData",
        "Local",
        "Temp",
        "tmp",
        "cache",
        ".cache",
        ".idea",
        ".vscode",
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ProjectRepository(db)

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

    def _get_git_info(self, git_root: Path) -> tuple[str | None, str | None]:
        """Get Git remote URL and default branch."""
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

    def _is_git_repo(self, path: Path) -> bool:
        """Check if a path is a Git repository root."""
        git_dir = path / ".git"
        return git_dir.exists() and (git_dir.is_dir() or git_dir.is_file())

    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from scanning."""
        # Only check the directory name itself, not parent paths
        if path.name in self.EXCLUDED_DIRS:
            return True
        return False

    def _scan_for_git_roots(self, root: Path, max_depth: int = 3) -> list[Path]:
        """Scan a root directory for Git repositories up to max_depth."""
        git_roots = []

        def scan_dir(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            if self._should_exclude(current):
                return
            if self._is_git_repo(current):
                git_roots.append(current)
                return
            try:
                for child in current.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        scan_dir(child, depth + 1)
            except (PermissionError, OSError):
                pass

        scan_dir(root, 0)
        return git_roots

    def discover_projects(self, roots: list[str]) -> list[DiscoveredProject]:
        """Discover projects from workspace roots."""
        discovered = []
        seen_canonical = set()

        for root_str in roots:
            root = Path(root_str)
            if not root.exists() or not root.is_dir():
                continue

            git_roots = self._scan_for_git_roots(root)

            for git_root in git_roots:
                canonical = str(git_root.resolve())
                if canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)

                name = git_root.name
                base_namespace = self._derive_namespace(name)
                namespace = self._resolve_namespace_collision(base_namespace)

                remote_url, default_branch = self._get_git_info(git_root)

                discovered.append(
                    DiscoveredProject(
                        name=name,
                        namespace=namespace,
                        root_path=str(git_root),
                        canonical_path=canonical,
                        git_root=str(git_root),
                        remote_url=remote_url,
                        default_branch=default_branch,
                    )
                )

        return discovered