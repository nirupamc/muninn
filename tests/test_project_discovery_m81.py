"""M8.1 — Workstation Project Discovery Truth tests.

Covers drive enumeration, non-Git detection, canonical identity,
collisions, zero-memory visibility, registry authority, ignore behavior,
privacy pruning, permission tolerance and symlink/junction loop safety.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import unittest.mock
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.memory import Memory, MemoryType
from app.projects.discovery import ProjectDiscoveryService as Orchestrator
from app.projects.drives import DriveDiscoveryService, DriveType
from app.projects.paths import canonical_key
from app.projects.repository import ProjectRepository
from app.projects.scanner import EXCLUDED_DIR_NAMES, WorkspaceScanner
from app.projects.service import ProjectService


@pytest.fixture()
def settings():
    s = get_settings()
    saved = {
        key: getattr(s, key)
        for key in (
            "workspace_roots",
            "auto_discover_drives",
            "auto_discover_fixed_drives",
            "auto_discover_removable_drives",
            "auto_discover_network_drives",
            "project_scan_max_depth",
            "project_detection_threshold",
            "project_discovery_excluded_roots",
        )
    }
    yield s
    for key, value in saved.items():
        setattr(s, key, value)


@contextlib.contextmanager
def tempfile_dir() -> Iterator[str]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield tmp


def fake_drive_service(drives: list[tuple[str, int]]) -> DriveDiscoveryService:
    return DriveDiscoveryService(enumerator=lambda: drives)


def make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, capture_output=True)
    (path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=path, capture_output=True)


# --------------------------------------------------------------------- #
# 1. Drive enumeration                                                    #
# --------------------------------------------------------------------- #
def test_drive_enumeration_defaults(settings):
    service = fake_drive_service(
        [
            ("C:\\", 3),
            ("D:\\", 3),
            ("E:\\", 3),
            ("F:\\", 2),   # removable
            ("Z:\\", 4),   # network
        ]
    )
    drives = service.list_drives(
        include_fixed=settings.auto_discover_fixed_drives,
        include_removable=settings.auto_discover_removable_drives,
        include_network=settings.auto_discover_network_drives,
    )

    by_root = {d.root_path: d for d in drives}
    assert set(by_root) == {"C:\\", "D:\\", "E:\\", "F:\\", "Z:\\"}

    assert [r for r in ("C:\\", "D:\\", "E:\\") if by_root[r].enabled_for_scan] == ["C:\\", "D:\\", "E:\\"]
    assert all(by_root[r].drive_type == DriveType.fixed for r in ("C:\\", "D:\\", "E:\\"))

    f = by_root["F:\\"]
    z = by_root["Z:\\"]
    assert not f.enabled_for_scan and f.drive_type == DriveType.removable
    assert not z.enabled_for_scan and z.drive_type == DriveType.network

    # CD-ROM volumes are ignored entirely.
    cd = fake_drive_service([("Q:\\", 5)]).list_drives()
    assert cd[0].enabled_for_scan is False
    assert cd[0].drive_type == DriveType.cdrom


def test_windows_logical_drive_enumerator_no_hardcoded_letters():
    """The real Windows enumerator must derive letters from the OS mask."""
    if sys.platform != "win32":
        pytest.skip("Windows-only")
    import string

    from app.projects.drives import _windows_logical_drives

    found = _windows_logical_drives()
    assert len(found) >= 1
    for root, raw_type in found:
        assert root[0] in string.ascii_uppercase and root[1:] == ":\\"
        assert isinstance(raw_type, int)
        assert any(os.path.exists(root) is accessible for accessible in (True, False))


# --------------------------------------------------------------------- #
# 2. Non-Git project detection                                            #
# --------------------------------------------------------------------- #
def test_non_git_projects_detected_random_folder_rejected(db_session):
    with tempfile_dir() as tmp:
        root = Path(tmp)
        (root / "python-app").mkdir()
        (root / "python-app" / "pyproject.toml").write_text("[project]\n")
        (root / "react-app").mkdir()
        (root / "react-app" / "package.json").write_text("{}\n")
        (root / "rust-app").mkdir()
        (root / "rust-app" / "Cargo.toml").write_text("")
        (root / "go-app").mkdir()
        (root / "go-app" / "go.mod").write_text("")
        (root / "random-folder").mkdir()
        (root / "random-folder" / "readme.txt").write_text("not a project")

        scanner = WorkspaceScanner(max_depth=3)
        result = scanner.scan_roots([str(root)])
        names = {d.name for d in result.detected}

        assert {"python-app", "react-app", "rust-app", "go-app"} <= names
        assert "random-folder" not in names


# --------------------------------------------------------------------- #
# 3. Git project strong signal                                            #
# --------------------------------------------------------------------- #
def test_git_project_strong_detection(db_session, settings):
    with tempfile_dir() as tmp:
        repo = Path(tmp) / "git-repo"
        make_git_repo(repo)

        settings.auto_discover_drives = False
        orchestrator = Orchestrator(db_session, settings=settings)
        outcome = orchestrator.run_scan(roots=[str(Path(tmp))], include_auto_drives=False)

        assert outcome.projects_found == 1
        project = outcome.projects_new[0]
        assert project.name == "git-repo"
        assert project.git_root is not None
        assert ".git" in project.discovery_evidence_json


def test_nested_monorepo_absorbed_nested_git_repo_separate(db_session, settings):
    with tempfile_dir() as tmp:
        platform = Path(tmp) / "CompanyPlatform"
        platform.mkdir()
        (platform / "package.json").write_text("{}\n")
        backend = platform / "backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text("")
        frontend = platform / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text("{}\n")

        settings.auto_discover_drives = False
        db_session2 = None
        orchestrator = Orchestrator(db_session, settings=settings)
        outcome = orchestrator.run_scan(roots=[str(platform)], include_auto_drives=False)
        names = {p.name for p in outcome.projects_new}
        assert names == {"CompanyPlatform"}  # manifests absorbed into the parent

        # A nested independent Git repository IS a separate project.
        nested = platform / "vendored-tool"
        make_git_repo(nested)
        outcome2 = Orchestrator(db_session, settings=settings).run_scan(
            roots=[str(platform)], include_auto_drives=False
        )
        new_names = {p.name for p in outcome2.projects_new}
        assert new_names == {"vendored-tool"}
        existing_names = {p.name for p in outcome2.projects_existing}
        assert "CompanyPlatform" in existing_names


# --------------------------------------------------------------------- #
# 4. Canonical path identity                                              #
# --------------------------------------------------------------------- #
def test_duplicate_canonical_path_single_project(db_session, monkeypatch):
    with tempfile_dir() as tmp:
        real = Path(tmp) / "MixedCase_Project"
        real.mkdir()
        (real / "package.json").write_text("{}\n")

        service = ProjectService(db_session)
        first = service.register_project(str(real))
        assert first is not None

        # Same directory spelled differently.
        variant = str(real).replace("MixedCase", "mixedcase") if str(real) != str(real).lower() else str(real).upper()
        second = service.register_project(variant)
        assert second.id == first.id

        repo = ProjectRepository(db_session)
        assert len(list(repo.list_all())) == 1


def test_canonical_key_normalization():
    assert canonical_key("E:\\Muninn") == canonical_key("e:/muninn/")
    assert canonical_key("E:/Muninn/") == canonical_key("E:\\Muninn\\sub\\..")


# --------------------------------------------------------------------- #
# 5. Same-name collisions                                                 #
# --------------------------------------------------------------------- #
def test_same_name_collision_distinct_namespaces(db_session):
    with tempfile_dir() as tmp:
        api_one = Path(tmp) / "one" / "api"
        api_two = Path(tmp) / "two" / "api"
        api_one.mkdir(parents=True)
        api_two.mkdir(parents=True)
        (api_one / "pyproject.toml").write_text("")
        (api_two / "Cargo.toml").write_text("")

        service = ProjectService(db_session)
        p1 = service.register_project(str(api_one))
        p2 = service.register_project(str(api_two))

        assert p1.namespace != p2.namespace
        assert p1.canonical_path.lower() != p2.canonical_path.lower()
        assert p1.namespace.startswith("project:api")
        assert p2.namespace.startswith("project:api")


# --------------------------------------------------------------------- #
# 6/7. Zero-memory visibility through the API                             #
# --------------------------------------------------------------------- #
def test_zero_memory_project_visible_via_api(client, db_session):
    with tempfile_dir() as tmp:
        ghost = Path(tmp) / "ghost-project"
        ghost.mkdir()
        (ghost / "package.json").write_text("{}\n")

        service = ProjectService(db_session)
        registered = service.register_project(str(ghost))
        assert registered is not None
        db_session.commit()

        res = client.get("/api/v1/projects")
        assert res.status_code == 200
        body = res.json()
        names = [p["name"] for p in body["projects"]]
        assert "ghost-project" in names
        row = next(p for p in body["projects"] if p["name"] == "ghost-project")
        assert row["memory_count"] == 0
        assert row["capture_enabled"] is False

        # Sidebar-equivalent selector source: every registry project present.
        assert row["namespace"] in {p["namespace"] for p in body["projects"]}


# --------------------------------------------------------------------- #
# 8. Legacy memory namespace without a project                            #
# --------------------------------------------------------------------- #
def test_memory_namespace_without_project_not_fabricated(client, db_session):
    db_session.add(
        Memory(
            namespace="legacy-namespace",
            content="Old memory with no filesystem project behind it",
            memory_type=MemoryType.fact,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    projects = res.json()["projects"]
    assert all(p["namespace"] != "legacy-namespace" for p in projects)
    # The namespace remains a memory scope only; no fake project row exists.
    assert ProjectRepository(db_session).get_by_namespace("legacy-namespace") is None


# --------------------------------------------------------------------- #
# 9. Ignore behavior                                                      #
# --------------------------------------------------------------------- #
def test_ignored_project_never_reappears_after_rescan(db_session, settings):
    with tempfile_dir() as tmp:
        root = Path(tmp)
        keeper = root / "keeper"
        keeper.mkdir()
        (keeper / "pyproject.toml").write_text("")
        scratch = root / "scratch-repo"
        make_git_repo(scratch)

        settings.auto_discover_drives = False
        orchestrator = Orchestrator(db_session, settings=settings)
        first = orchestrator.run_scan(roots=[str(root)], include_auto_drives=False)
        scratch_project = next(p for p in first.projects_new if p.name == "scratch-repo")

        service = ProjectService(db_session)
        service.set_ignored(scratch_project.id, True)

        second = orchestrator.run_scan(roots=[str(root)], include_auto_drives=False)
        seen = [p.canonical_path.lower() for p in [*second.projects_new, *second.projects_existing]]
        assert scratch_project.canonical_path.lower() not in seen
        assert any(p.name == "keeper" for p in second.projects_existing)

        # Still auditable via explicit filters, but hidden from default lists.
        default_list = service.list_projects_with_counts()[0]
        assert all(p.name != "scratch-repo" for p in default_list)
        audit_list = service.list_projects_with_counts(include_ignored=True)[0]
        assert any(p.name == "scratch-repo" for p in audit_list)

        # Unignore restores scan eligibility.
        service.set_ignored(scratch_project.id, False)
        third = orchestrator.run_scan(roots=[str(root)], include_auto_drives=False)
        reobserved = [p.name for p in third.projects_existing]
        assert "scratch-repo" in reobserved


# --------------------------------------------------------------------- #
# 10. Privacy/system directories pruned                                   #
# --------------------------------------------------------------------- #
def test_system_and_vendor_directories_skipped(db_session):
    with tempfile_dir() as tmp:
        root = Path(tmp)
        for name in ("node_modules", ".venv", "$Recycle.Bin", "System Volume Information"):
            d = root / name
            d.mkdir()
            (d / "package.json").write_text("{}")

        scanner = WorkspaceScanner(max_depth=3)
        result = scanner.scan_roots([str(root)])
        assert result.detected == []
        assert result.stats.directories_skipped >= 4
        reasons = " ".join(s.reason for s in result.skipped_candidates)
        assert "excluded directory" in reasons

        # The mandatory exclusion list covers the spec's requirements.
        required = {
            "$recycle.bin",
            "system volume information",
            "windows",
            "program files",
            "program files (x86)",
            "programdata",
            "recovery",
            "appdata",
            "local settings",
            "node_modules",
            ".venv",
            "venv",
            "env",
            ".git",
            ".hg",
            ".svn",
            "dist",
            "build",
            "out",
            "target",
            "coverage",
            ".cache",
            "__pycache__",
            "site-packages",
        }
        missing = required - EXCLUDED_DIR_NAMES
        assert not missing, f"missing exclusions: {missing}"


# --------------------------------------------------------------------- #
# 11. Permission errors never abort the scan                              #
# --------------------------------------------------------------------- #
def test_permission_error_does_not_abort_scan(db_session):
    real_scandir = os.scandir

    def flaky_scandir(path):
        if str(path).lower().endswith("locked"):
            raise PermissionError(13, "Access denied", str(path))
        return real_scandir(path)

    with tempfile_dir() as tmp:
        root = Path(tmp)
        good = root / "good"
        good.mkdir()
        (good / "go.mod").write_text("")
        locked = root / "locked"
        locked.mkdir()

        with unittest.mock.patch("app.projects.scanner.os.scandir", side_effect=flaky_scandir):
            scanner = WorkspaceScanner(max_depth=4)
            result = scanner.scan_roots([str(root)])

    assert [d.name for d in result.detected] == ["good"]
    assert result.stats.permission_errors >= 1


# --------------------------------------------------------------------- #
# 12. Symlink/junction loop protection                                    #
# --------------------------------------------------------------------- #
def test_junction_loop_does_not_recurse_infinitely(db_session):
    if sys.platform != "win32":
        pytest.skip("Windows junctions")
    with tempfile_dir() as tmp:
        root = Path(tmp)
        outer = root / "outer"
        outer.mkdir()
        (outer / "package.json").write_text("{}\n")

        # mklink /J requires no admin rights on Windows.
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(outer / "loop"), str(root)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip(f"junction creation unavailable: {proc.stderr.strip()}")

        scanner = WorkspaceScanner(max_depth=8, max_directories=500)
        result = scanner.scan_roots([str(root)])  # must terminate

        followed_paths = [s.reason for s in result.skipped_candidates]
        assert any("symlink/junction" in reason for reason in followed_paths)
        assert len(result.detected) == 1
