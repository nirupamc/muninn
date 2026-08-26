"""Bounded workstation directory scanner for project discovery.

Never naively walks an entire OS tree: aggressive directory pruning,
depth/directory caps, symlink/junction loop protection, permission-error
tolerance, and bounded diagnostics. Filenames only — never file contents.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from app.projects.detectors import DEFAULT_THRESHOLD, ProjectEvidence, detect_evidence
from app.projects.paths import canonical_key

# System/vendor/cache directories never worth traversing.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        # OS/system volumes and locations
        "$recycle.bin",
        "system volume information",
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "recovery",
        "appdata",
        "local settings",
        "system32",
        # VCS internals / tooling metadata
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".gradle",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        # Dependency trees / virtualenvs
        "node_modules",
        "bower_components",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "vendor",
        # Build outputs
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        "obj",
        ".next",
        ".nuxt",
        # Caches (incl. model caches)
        ".cache",
        "cache",
        "caches",
        ".huggingface",
        "huggingface",
        ".ollama",
        ".torch",
        # Temporary locations
        "tmp",
        "temp",
        "$windows.~bt",
        "windows.old",
    }
)

MAX_SKIPPED_ROWS = 200


@dataclass
class DetectedProject:
    """A candidate directory that crossed the detection threshold."""

    path: str
    name: str
    evidence: ProjectEvidence
    git_root: str | None
    remote_url: str | None
    default_branch: str | None


@dataclass
class SkippedCandidate:
    """A bounded diagnostic row explaining why a directory was skipped."""

    path: str
    reason: str


@dataclass
class ScanStats:
    directories_considered: int = 0
    directories_skipped: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    permission_errors: int = 0
    max_depth_reached: int = 0


@dataclass
class ScanResult:
    """Structured result of one discovery run over one or more roots."""

    roots: list[str] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)
    detected: list[DetectedProject] = field(default_factory=list)
    skipped_candidates: list[SkippedCandidate] = field(default_factory=list)

    def note_skip(self, path: str, reason: str) -> None:
        self.stats.directories_skipped += 1
        self.stats.skipped_by_reason[reason] = self.stats.skipped_by_reason.get(reason, 0) + 1
        if len(self.skipped_candidates) < MAX_SKIPPED_ROWS:
            self.skipped_candidates.append(SkippedCandidate(path=path, reason=reason))


def _is_reparse_point(entry: os.DirEntry) -> bool:
    """True for symlinks/junctions/mount points — never recurse into them."""
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    if sys.platform == "win32":
        try:
            st = entry.stat(follow_symlinks=False)
            return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return True
    try:
        return entry.stat(follow_symlinks=False).st_mode & stat.S_IFMT() == stat.S_IFLNK
    except OSError:
        return True


def get_git_info(git_root: str) -> tuple[str | None, str | None]:
    """Read remote URL and default branch; failures are non-fatal."""
    remote_url = None
    default_branch = None
    popen_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=popen_flags,
        )
        if result.returncode == 0:
            remote_url = result.stdout.strip() or None
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=popen_flags,
        )
        if result.returncode == 0:
            default_branch = result.stdout.strip() or None
    except Exception:
        pass
    return remote_url, default_branch


GitInfoResolver = Callable[[str], tuple[str | None, str | None]]


class WorkspaceScanner:
    """Depth-bounded, pruned filesystem scan producing project candidates."""

    def __init__(
        self,
        *,
        max_depth: int = 6,
        max_directories: int = 200000,
        threshold: int = DEFAULT_THRESHOLD,
        excluded_dir_names: frozenset[str] = EXCLUDED_DIR_NAMES,
        extra_excluded_dirs: set[str] | None = None,
        excluded_path_keys: set[str] | None = None,
        git_info_resolver: GitInfoResolver = get_git_info,
    ) -> None:
        self.max_depth = max(0, max_depth)
        self.max_directories = max(1, max_directories)
        self.threshold = threshold
        self.excluded = {d.lower() for d in excluded_dir_names} | {
            d.lower() for d in (extra_excluded_dirs or set())
        }
        self.excluded_path_keys = excluded_path_keys or set()
        self._git_info = git_info_resolver

    def scan_roots(self, roots: list[str]) -> ScanResult:
        result = ScanResult(roots=list(roots))
        seen_global: set[str] = set()
        for root_str in roots:
            self._scan_tree(root_str, result, seen_global)
        return result

    def _scan_tree(self, root_str: str, result: ScanResult, seen_global: set[str]) -> None:
        if len(seen_global) >= self.max_directories:
            result.note_skip(root_str, "directory cap reached")
            return
        if not os.path.isdir(root_str):
            result.note_skip(root_str, "root missing or not a directory")
            return
        if canonical_key(root_str) in self.excluded_path_keys:
            result.note_skip(root_str, "root excluded")
            return

        try:
            entries = sorted(os.scandir(root_str), key=lambda e: e.name.lower())
        except (PermissionError, OSError):
            result.stats.permission_errors += 1
            result.note_skip(root_str, "root unreadable")
            return

        self._consider(root_str, depth=0, inside_project=None, result=result, seen_global=seen_global)

    def _consider(
        self,
        current: str,
        *,
        depth: int,
        inside_project: str | None,
        result: ScanResult,
        seen_global: set[str],
    ) -> None:
        """Evaluate one directory, then recurse into eligible children."""
        current_key = canonical_key(current)
        if current_key in seen_global:
            return
        seen_global.add(current_key)
        if len(seen_global) > self.max_directories:
            result.note_skip(current, "directory cap reached")
            return

        result.stats.directories_considered += 1
        result.stats.max_depth_reached = max(result.stats.max_depth_reached, depth)

        evidence = detect_evidence(current)
        qualified = evidence is not None and evidence.score >= self.threshold

        next_inside_project = inside_project
        if qualified and evidence is not None:
            if inside_project is not None and ".git" not in evidence.markers:
                # Manifest-only child inside an already-detected project is
                # part of the parent (e.g. monorepo frontend/backend folders).
                result.note_skip(current, f"nested within project {inside_project}")
            else:
                git_root = current if ".git" in evidence.markers else None
                remote_url = default_branch = None
                if git_root:
                    remote_url, default_branch = self._git_info(git_root)
                result.detected.append(
                    DetectedProject(
                        path=current,
                        name=os.path.basename(current.rstrip("\\/")) or current,
                        evidence=evidence,
                        git_root=git_root,
                        remote_url=remote_url,
                        default_branch=default_branch,
                    )
                )
                next_inside_project = current

        if depth >= self.max_depth:
            return

        try:
            children = sorted(os.scandir(current), key=lambda e: e.name.lower())
        except PermissionError:
            result.stats.permission_errors += 1
            result.note_skip(current, "permission denied")
            return
        except OSError:
            result.stats.permission_errors += 1
            result.note_skip(current, "unreadable")
            return

        for child in children:
            try:
                if not child.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                result.stats.permission_errors += 1
                continue
            name_lower = child.name.lower()
            if name_lower in self.excluded:
                result.note_skip(child.path, f"excluded directory ({child.name})")
                continue
            if _is_reparse_point(child):
                result.note_skip(child.path, "symlink/junction not followed")
                continue
            if canonical_key(child.path) in self.excluded_path_keys:
                result.note_skip(child.path, f"user-excluded root ({child.name})")
                continue
            self._consider(
                child.path,
                depth=depth + 1,
                inside_project=next_inside_project,
                result=result,
                seen_global=seen_global,
            )
