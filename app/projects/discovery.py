"""Workstation project discovery orchestration.

Combines drive enumeration, bounded scanning and evidence-based detection
into structured scan runs with diagnostics. The Project table is the
authoritative registry; memory namespaces are never used as a project list.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.project import Project
from app.projects.drives import DiscoveredDrive, DriveDiscoveryService, canonical_root
from app.projects.paths import canonical_key
from app.projects.repository import ProjectRepository
from app.projects.scanner import DetectedProject, ScanResult, WorkspaceScanner

logger = logging.getLogger("munin.projects.discovery")


@dataclass
class DriveReport:
    """Per-drive outcome for diagnostics."""

    root_path: str
    drive_type: str
    status: str  # scanned | skipped | unavailable
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path,
            "drive_type": self.drive_type,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class ScanOutcome:
    """Full result of one discovery run."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    drives: list[DriveReport] = field(default_factory=list)
    roots_scanned: list[str] = field(default_factory=list)
    directories_considered: int = 0
    directories_skipped: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    permission_errors: int = 0
    max_depth_reached: int = 0
    projects_found: int = 0
    projects_new: list[Project] = field(default_factory=list)
    projects_existing: list[Project] = field(default_factory=list)
    skipped_candidates: list[dict[str, str]] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        if self.finished_at is None:
            return 0
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def to_summary(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "drives": [d.to_dict() for d in self.drives],
            "roots_scanned": self.roots_scanned,
            "directories_considered": self.directories_considered,
            "directories_skipped": self.directories_skipped,
            "skipped_by_reason": self.skipped_by_reason,
            "permission_errors": self.permission_errors,
            "max_depth_reached": self.max_depth_reached,
            "projects_found": self.projects_found,
            "projects_new": len(self.projects_new),
            "projects_existing": len(self.projects_existing),
            "skipped_candidates": self.skipped_candidates,
        }


class ScanStatusTracker:
    """Process-wide, thread-safe tracker for the latest/running scan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._last: dict[str, Any] | None = None

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def finish(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self._running = False
            self._last = summary

    def fail(self) -> None:
        with self._lock:
            self._running = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"scan_in_progress": self._running, "last_scan": self._last}


SCAN_STATUS = ScanStatusTracker()


def _split_paths(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(";") if p.strip()]


class ProjectDiscoveryService:
    """Discovers projects from workspace roots and eligible drives."""

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.repo = ProjectRepository(db)
        self.settings = settings or get_settings()
        self.drive_service = DriveDiscoveryService()

    # ------------------------------------------------------------------ #
    # Legacy-compatible API (Git-root style results, evidence-based now)  #
    # ------------------------------------------------------------------ #
    def discover_projects(self, roots: list[str]) -> list[DetectedProject]:
        """Scan the given roots and return detected candidates (no persistence)."""
        scanner = self._build_scanner()
        result = scanner.scan_roots(roots)
        return result.detected

    # ------------------------------------------------------------------ #
    # Full workstation scan                                               #
    # ------------------------------------------------------------------ #
    def run_scan(
        self,
        *,
        roots: list[str] | None = None,
        include_auto_drives: bool = True,
        persist_report: bool = True,
    ) -> ScanOutcome:
        """Run one bounded discovery pass over priority roots + eligible drives."""
        if not SCAN_STATUS.start():
            raise RuntimeError("A project discovery scan is already running")

        outcome = ScanOutcome()
        s = self.settings
        try:
            if not s.project_discovery_enabled:
                outcome.finished_at = datetime.now(UTC)
                summary = outcome.to_summary()
                if persist_report:
                    self._persist_report(outcome)
                SCAN_STATUS.finish(summary)
                return outcome

            excluded_root_keys = {
                canonical_key(r) for r in _split_paths(s.project_discovery_excluded_roots)
            }

            priority_roots = roots if roots else _split_paths(s.workspace_roots)

            drives: list[DiscoveredDrive] = []
            if include_auto_drives and s.auto_discover_drives:
                drives = self.drive_service.list_drives(
                    include_fixed=s.auto_discover_fixed_drives,
                    include_removable=s.auto_discover_removable_drives,
                    include_network=s.auto_discover_network_drives,
                    excluded_roots=_split_paths(s.project_discovery_excluded_roots),
                )
                for drive in drives:
                    if not drive.accessible:
                        outcome.drives.append(
                            DriveReport(drive.root_path, drive.drive_type.value, "unavailable", drive.skip_reason)
                        )
                        continue
                    if drive.enabled_for_scan:
                        outcome.drives.append(
                            DriveReport(drive.root_path, drive.drive_type.value, "scanned")
                        )
                    else:
                        outcome.drives.append(
                            DriveReport(drive.root_path, drive.drive_type.value, "skipped", drive.skip_reason)
                        )

            scan_roots = self._merge_roots(priority_roots, drives)

            ignored_keys = self.repo.list_ignored_path_keys()
            scanner = self._build_scanner(excluded_keys=excluded_root_keys | ignored_keys)
            result = scanner.scan_roots(scan_roots)

            outcome.roots_scanned = scan_roots
            outcome.directories_considered = result.stats.directories_considered
            outcome.directories_skipped = result.stats.directories_skipped
            outcome.skipped_by_reason = dict(result.stats.skipped_by_reason)
            outcome.permission_errors = result.stats.permission_errors
            outcome.max_depth_reached = result.stats.max_depth_reached
            outcome.skipped_candidates = [
                {"path": sk.path, "reason": sk.reason} for sk in result.skipped_candidates
            ]

            for detected in result.detected:
                self._register_detected(detected, outcome)

            self._annotate_same_remote(outcome)

            outcome.projects_found = len(result.detected)
            outcome.finished_at = datetime.now(UTC)

            if persist_report:
                self._persist_report(outcome)
            SCAN_STATUS.finish(outcome.to_summary())
            return outcome
        except Exception:
            SCAN_STATUS.fail()
            raise

    def _build_scanner(self, excluded_keys: set[str] | None = None) -> WorkspaceScanner:
        s = self.settings
        return WorkspaceScanner(
            max_depth=s.project_scan_max_depth,
            max_directories=s.project_scan_max_directories,
            threshold=s.project_detection_threshold,
            extra_excluded_dirs={
                d for d in s.project_discovery_extra_excluded_dirs.split(",") if d.strip()
            },
            excluded_path_keys=excluded_keys or set(),
        )

    def _merge_roots(self, priority_roots: list[str], drives: list[DiscoveredDrive]) -> list[str]:
        """Priority roots win over overlapping auto-drive scans."""
        merged: list[str] = []
        keys: list[tuple[str, str]] = []

        def add_root(path: str, source: str) -> None:
            key = canonical_key(path)
            if any(key == k or key.startswith(k.rstrip("\\") + os.sep) for k, _ in keys):
                return  # already covered by an ancestor root
            # drop previously added roots contained inside this one
            merged.clear()
            keys[:] = [(k, src) for k, src in keys if not k.startswith(key.rstrip("\\") + os.sep)]
            merged.append(path)
            keys.append((key, source))

        for root in priority_roots:
            add_root(root, "priority")

        if self.settings.auto_discover_drives:
            for drive in drives:
                if drive.enabled_for_scan and drive.accessible:
                    add_root(drive.root_path, "drive")

        return merged

    def _derive_namespace(self, name: str) -> str:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        slug = slug.strip("-")
        return f"project:{slug}" if slug else "project:unnamed"

    def _resolve_namespace_collision(self, base_namespace: str) -> str:
        namespace = base_namespace
        counter = 1
        while self.repo.get_by_namespace(namespace):
            counter += 1
            namespace = f"{base_namespace}-{counter}"
        return namespace

    def _register_detected(self, detected: DetectedProject, outcome: ScanOutcome) -> Project | None:
        from app.projects.service import ProjectService  # local import to avoid cycle

        existing = self.repo.get_by_canonical_path(detected.path)
        if existing:
            existing.git_root = detected.git_root or existing.git_root
            if detected.remote_url:
                existing.remote_url = detected.remote_url
            if detected.default_branch:
                existing.default_branch = detected.default_branch
            existing.discovery_evidence_json = list(detected.evidence.markers)
            self.repo.touch_discovered(existing.id)
            outcome.projects_existing.append(existing)
            return existing

        service = ProjectService(self.db)
        project = service.register_project(
            detected.path,
            name=detected.name,
            enable_capture=True,
            discovery_source="auto_drive" if _is_direct_drive_child(detected.path) else "workspace_root",
            discovery_evidence=list(detected.evidence.markers),
            git_root=detected.git_root,
            remote_url=detected.remote_url,
            default_branch=detected.default_branch,
        )
        if project is not None:
            outcome.projects_new.append(project)
        return project

    def _annotate_same_remote(self, outcome: ScanOutcome) -> None:
        """Surface clone/duplicate relationships by shared Git remote URL."""
        by_remote: dict[str, list[Project]] = {}
        for project in [*outcome.projects_new, *outcome.projects_existing]:
            url = (project.remote_url or "").strip()
            if url:
                by_remote.setdefault(url, []).append(project)

        for url, group in by_remote.items():
            if len(group) < 2:
                continue
            paths = [p.canonical_path for p in group]
            for project in group:
                others = sorted(set(paths) - {project.canonical_path})
                project.metadata_["same_remote"] = True
                project.metadata_["same_remote_with"] = others
                project.metadata_["same_remote_url"] = url

    def _persist_report(self, outcome: ScanOutcome) -> None:
        path = Path(self.settings.discovery_report_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(outcome.to_summary(), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist discovery report: %s", exc)


def _is_direct_drive_child(path: str) -> bool:
    parent = os.path.dirname(os.path.abspath(path))
    return len(parent) <= 3  # e.g. "E:\" — direct child of a drive root


def get_discovery_status() -> dict[str, Any]:
    """Last-scan summary + live progress for the status API."""
    status = SCAN_STATUS.snapshot()
    report_path = Path(get_settings().discovery_report_path)
    if status["last_scan"] is None and report_path.exists():
        try:
            status["last_scan"] = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status["last_scan"] = None
    return status


__all__ = [
    "ProjectDiscoveryService",
    "ScanOutcome",
    "DriveReport",
    "get_discovery_status",
    "canonical_root",
]
