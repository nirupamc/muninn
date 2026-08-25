"""Git capture adapter."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.capture.adapters.base import CaptureAdapter, AdapterHealth
from app.models.capture import CaptureSource, CaptureEventType
from app.models.project import Project
from sqlalchemy.orm.attributes import flag_modified


@dataclass
class GitCheckpoint:
    """Git adapter checkpoint state."""

    last_commit_sha: str | None = None
    last_branch: str | None = None

    def to_json(self) -> str:
        return json.dumps({
            "last_commit_sha": self.last_commit_sha,
            "last_branch": self.last_branch,
        })

    @classmethod
    def from_json(cls, data: str) -> GitCheckpoint:
        obj = json.loads(data)
        return cls(
            last_commit_sha=obj.get("last_commit_sha"),
            last_branch=obj.get("last_branch"),
        )


class GitAdapter(CaptureAdapter):
    """Git capture adapter for capturing commits and branch changes."""

    name = CaptureSource.git

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self._checkpoint = GitCheckpoint()

    def _load_checkpoint(self, project: Project) -> None:
        """Load checkpoint from project metadata."""
        if project.metadata_:
            cp_data = project.metadata_.get("git_checkpoint")
            if cp_data:
                self._checkpoint = GitCheckpoint.from_json(cp_data)

    def _save_checkpoint(self, project: Project, db: Session) -> None:
        """Save checkpoint to project metadata."""
        project.metadata_["git_checkpoint"] = self._checkpoint.to_json()
        flag_modified(project, "metadata_")
        db.flush()

    def available(self) -> bool:
        """Check if Git is available for this project."""
        if not self.project.git_root:
            return False
        git_dir = Path(self.project.git_root) / ".git"
        return git_dir.exists()

    def _run_git(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run a git command."""
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.project.git_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _get_current_branch(self) -> str | None:
        """Get the current branch name."""
        result = self._run_git(["symbolic-ref", "--short", "HEAD"])
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _get_head_commit(self) -> str | None:
        """Get the current HEAD commit SHA."""
        result = self._run_git(["rev-parse", "HEAD"])
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _get_commit_info(self, sha: str) -> dict[str, Any] | None:
        """Get commit information."""
        result = self._run_git([
            "show",
            "--no-patch",
            "--format=%H|%an|%ae|%ad|%s",
            "--date=iso-strict",
            sha,
        ])
        if result.returncode != 0:
            return None

        parts = result.stdout.strip().split("|", 4)
        if len(parts) != 5:
            return None

        return {
            "sha": parts[0],
            "author": parts[1],
            "author_email": parts[2],
            "date": parts[3],
            "message": parts[4],
        }

    def _get_changed_files(self, sha: str) -> list[str]:
        """Get files changed in a commit."""
        result = self._run_git(["show", "--name-only", "--pretty=format:", sha])
        if result.returncode != 0:
            return []
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return files

    def _get_new_commits(self, since_sha: str | None) -> list[str]:
        """Get new commit SHAs since the given SHA."""
        if since_sha:
            args = ["log", "--oneline", "--reverse", f"{since_sha}..HEAD"]
        else:
            # No checkpoint yet - get all commits
            args = ["log", "--oneline", "--reverse"]

        result = self._run_git(args)
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                sha = line.split()[0]
                commits.append(sha)
        return commits

    def discover_events(self, project: Project, db: Session) -> list[dict[str, Any]]:
        """Discover new Git commits since last checkpoint."""
        # Load checkpoint from current project state
        self._load_checkpoint(project)

        events = []

        if not self.available():
            return events

        current_branch = self._get_current_branch()
        head_sha = self._get_head_commit()

        if not head_sha:
            return events

        # Check for branch change
        if self._checkpoint.last_branch and current_branch != self._checkpoint.last_branch:
            events.append({
                "event_type": CaptureEventType.git_branch_change,
                "content": f"Branch changed from {self._checkpoint.last_branch} to {current_branch}",
                "metadata": {
                    "old_branch": self._checkpoint.last_branch,
                    "new_branch": current_branch,
                },
                "occurred_at": datetime.now(UTC),
                "fingerprint": f"branch_change|{self._checkpoint.last_branch}|{current_branch}",
            })
            self._checkpoint.last_branch = current_branch

        # Get new commits
        new_commits = self._get_new_commits(self._checkpoint.last_commit_sha)

        for sha in new_commits:
            info = self._get_commit_info(sha)
            if not info:
                continue

            changed_files = self._get_changed_files(sha)

            occurred_at = datetime.now(UTC)
            try:
                occurred_at = datetime.fromisoformat(info["date"].replace("Z", "+00:00"))
            except Exception:
                pass

            events.append({
                "event_type": CaptureEventType.git_commit,
                "content": f"Project {project.name} commit:\n\"{info['message']}\"",
                "metadata": {
                    "commit_sha": sha,
                    "author": info["author"],
                    "author_email": info["author_email"],
                    "branch": current_branch,
                    "changed_files": changed_files,
                },
                "occurred_at": occurred_at,
                "fingerprint": f"git_commit|{sha}",
            })

            self._checkpoint.last_commit_sha = sha

        if events:
            self._save_checkpoint(project, db)

        return events

    def checkpoint(self, project: Project, db: Session, event_data: dict[str, Any]) -> None:
        """Update checkpoint after processing an event."""
        self._save_checkpoint(project, db)

    def health(self) -> AdapterHealth:
        """Get adapter health status."""
        try:
            avail = self.available()
            head = self._get_head_commit() if avail else None
            branch = self._get_current_branch() if avail else None
            return AdapterHealth(
                name=self.name.value,
                available=avail,
                last_check=datetime.now(),
                metadata={
                    "head": head,
                    "branch": branch,
                    "last_checkpoint": self._checkpoint.last_commit_sha,
                },
            )
        except Exception as e:
            return AdapterHealth(
                name=self.name.value,
                available=False,
                last_check=datetime.now(),
                error=str(e),
            )