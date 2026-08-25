"""Filesystem capture adapter with batched events."""

from __future__ import annotations

import json
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.capture.adapters.base import CaptureAdapter, AdapterHealth
from app.models.capture import CaptureSource, CaptureEventType
from app.models.project import Project
from sqlalchemy.orm.attributes import flag_modified


@dataclass
class FilesystemCheckpoint:
    """Filesystem adapter checkpoint state."""

    last_scan_time: float = 0.0
    known_files: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "last_scan_time": self.last_scan_time,
            "known_files": self.known_files,
        })

    @classmethod
    def from_json(cls, data: str) -> FilesystemCheckpoint:
        obj = json.loads(data)
        return cls(
            last_scan_time=obj.get("last_scan_time", 0.0),
            known_files=obj.get("known_files", {}),
        )


class FilesystemAdapter(CaptureAdapter):
    """Filesystem capture adapter with batched change detection."""

    name = CaptureSource.filesystem

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.settings = get_settings()
        self._checkpoint = FilesystemCheckpoint()
        self._pending_changes: dict[str, float] = {}
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _load_checkpoint(self, project: Project) -> None:
        """Load checkpoint from project metadata."""
        if project.metadata_:
            cp_data = project.metadata_.get("filesystem_checkpoint")
            if cp_data:
                self._checkpoint = FilesystemCheckpoint.from_json(cp_data)

    def _save_checkpoint(self, project: Project, db: Session) -> None:
        """Save checkpoint to project metadata."""
        project.metadata_["filesystem_checkpoint"] = self._checkpoint.to_json()
        flag_modified(project, "metadata_")
        db.flush()

    def available(self) -> bool:
        """Check if filesystem watching is available."""
        return self.project.root_path is not None and Path(self.project.root_path).exists()

    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded."""
        import fnmatch
        excluded = self.settings.capture_excluded_paths.split(",")
        # Check the filename and all parent directory names
        for part in path.parts:
            for pattern in excluded:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def _scan_changes(self) -> list[Path]:
        """Scan for changed files since last checkpoint."""
        root = Path(self.project.root_path)
        if not root.exists():
            return []

        changed = []
        current_time = time.time()

        try:
            for file_path in root.rglob("*"):
                if file_path.is_symlink():
                    continue
                if self._should_exclude(file_path):
                    continue
                if not file_path.is_file():
                    continue

                rel_path = file_path.relative_to(root)
                rel_str = str(rel_path)

                stat = file_path.stat()
                mtime = stat.st_mtime

                if rel_str not in self._checkpoint.known_files:
                    # New file
                    if mtime > self._checkpoint.last_scan_time:
                        changed.append(file_path)
                        self._checkpoint.known_files[rel_str] = mtime
                elif mtime > self._checkpoint.known_files[rel_str]:
                    # Modified file
                    changed.append(file_path)
                    self._checkpoint.known_files[rel_str] = mtime

        except (PermissionError, OSError):
            pass

        return changed

    def _debounced_batch(self) -> None:
        """Process pending changes as a batch."""
        with self._lock:
            if not self._pending_changes:
                return

            changed_files = list(self._pending_changes.keys())
            self._pending_changes.clear()

            # This will be called by the capture manager
            # We store the batch for the manager to pick up
            self._last_batch = {
                "files": changed_files,
                "occurred_at": datetime.now(UTC),
            }

    def discover_events(self, project: Project, db: Session) -> list[dict[str, Any]]:
        """Discover filesystem changes, batching them."""
        # Load checkpoint from current project state
        self._load_checkpoint(project)
        
        if not self.available() or not self.settings.capture_filesystem_enabled:
            return []

        events = []

        # Scan for immediate changes
        changed = self._scan_changes()
        if changed:
            with self._lock:
                current_time = time.time()
                for f in changed:
                    rel_str = str(f.relative_to(Path(self.project.root_path)))
                    self._pending_changes[rel_str] = current_time

        # Check if we have a completed batch
        if hasattr(self, "_last_batch"):
            batch = self._last_batch
            delattr(self, "_last_batch")

            file_list = "\n".join(sorted(batch["files"]))
            import hashlib
            fingerprint = hashlib.sha256(
                f"{project.id}|filesystem|file_batch_changed|{file_list}".encode()
            ).hexdigest()[:64]

            content_lines = ["Recent project files changed:"]
            content_lines.extend(f"  {f}" for f in sorted(batch["files"]))

            events.append({
                "event_type": CaptureEventType.file_batch_changed,
                "content": "\n".join(content_lines),
                "metadata": {
                    "changed_files": batch["files"],
                    "file_count": len(batch["files"]),
                    "working_directory": project.root_path,
                },
                "occurred_at": batch["occurred_at"],
                "fingerprint": fingerprint,
            })

            # Update checkpoint
            self._checkpoint.last_scan_time = time.time()
            self._save_checkpoint(project, db)

        return events

    def checkpoint(self, project: Project, db: Session, event_data: dict[str, Any]) -> None:
        """Update checkpoint after processing an event."""
        self._save_checkpoint(project, db)

    def health(self) -> AdapterHealth:
        """Get adapter health status."""
        return AdapterHealth(
            name=self.name.value,
            available=self.available(),
            last_check=datetime.now(),
            metadata={
                "root": self.project.root_path,
                "pending_changes": len(self._pending_changes),
                "known_files": len(self._checkpoint.known_files),
                "debounce_seconds": self.settings.capture_filesystem_debounce_seconds,
            },
        )