"""M8.1 Workstation Project Discovery evaluation script."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest.mock
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base, create_db_engine
from app.projects.discovery import ProjectDiscoveryService as Orchestrator
from app.projects.drives import DriveDiscoveryService, DriveType
from app.projects.service import ProjectService


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(name: str, passed: bool, details: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if details:
        print(f"       {details}")


def make_git_repo(path: Path) -> None:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=path, capture_output=True)


def run_evaluation() -> int:
    print_header("MUNIN M8.1 PROJECT DISCOVERY EVALUATION")

    results = {
        "drive_enumeration_accuracy": 0.0,
        "project_detection_precision": 0.0,
        "project_detection_recall": 0.0,
        "duplicate_project_count": -1,
        "zero_memory_visibility_success_rate": 0.0,
        "ignored_project_reappearance_count": -1,
        "permission_error_crash_count": -1,
    }

    total_tests = 0
    passed_tests = 0

    workdir = tempfile.mkdtemp(prefix="munin_m81_eval_")
    engine = create_db_engine(f"sqlite:///{workdir}/eval.db")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # ---------------------------------------------------------------- #
    print_header("TEST 1: Drive Enumeration")
    total_tests += 1
    try:
        fake_drives = [
            ("C:\\", 3),
            ("D:\\", 3),
            ("E:\\", 3),
            ("F:\\", 2),   # removable
            ("Z:\\", 4),   # network
        ]
        service = DriveDiscoveryService(enumerator=lambda: fake_drives)
        drives = service.list_drives(include_fixed=True, include_removable=False, include_network=False)
        eligible = sorted(d.root_path for d in drives if d.enabled_for_scan)
        expected = ["C:\\", "D:\\", "E:\\"]
        ok = eligible == expected
        skipped_types = {d.root_path: d.drive_type for d in drives if not d.enabled_for_scan}
        ok = ok and skipped_types.get("F:\\") == DriveType.removable and skipped_types.get("Z:\\") == DriveType.network
        results["drive_enumeration_accuracy"] = 1.0 if ok else 0.0
        passed_tests += ok
        print_result(
            "C/D/E scanned, F removable skipped, Z network skipped",
            ok,
            f"eligible={eligible} skipped={ {k: v.value for k, v in skipped_types.items()} }",
        )
    except Exception as exc:  # pragma: no cover
        print_result("Drive enumeration", False, str(exc))

    # ---------------------------------------------------------------- #
    print_header("TEST 2: Non-Git Project Detection (precision/recall)")
    total_tests += 1
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            expected_projects = {"python-app", "react-app", "rust-app", "go-app"}
            (root / "python-app").mkdir()
            (root / "python-app" / "pyproject.toml").write_text("[project]\nname='x'\n")
            (root / "react-app").mkdir()
            (root / "react-app" / "package.json").write_text("{}")
            (root / "rust-app").mkdir()
            (root / "rust-app" / "Cargo.toml").write_text("")
            (root / "go-app").mkdir()
            (root / "go-app" / "go.mod").write_text("")
            (root / "random-folder").mkdir()
            (root / "random-folder" / "readme.txt").write_text("hi")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "package.json").write_text("{}")
            (root / "$recycle.bin").mkdir()

            settings = get_settings()
            original = {
                "workspace_roots": settings.workspace_roots,
                "auto_discover_drives": settings.auto_discover_drives,
                "max_depth": settings.project_scan_max_depth,
            }
            settings.workspace_roots = str(root)
            settings.auto_discover_drives = False

            try:
                db = TestSession()
                try:
                    orchestrator = Orchestrator(db, settings=settings)
                    outcome = orchestrator.run_scan(include_auto_drives=False, persist_report=False)
                    found = {p.name for p in outcome.projects_new}
                    tp = len(found & expected_projects)
                    fp = len(found - expected_projects)
                    fn = len(expected_projects - found)
                    results["project_detection_precision"] = tp / max(1, tp + fp)
                    results["project_detection_recall"] = tp / max(1, tp + fn)
                    ok = (
                        "random-folder" not in found
                        and results["project_detection_precision"] == 1.0
                        and results["project_detection_recall"] == 1.0
                    )
                    passed_tests += ok
                    print_result(
                        "Detected python/react/rust/go apps, rejected random-folder",
                        ok,
                        f"found={sorted(found)} precision={results['project_detection_precision']:.2f} recall={results['project_detection_recall']:.2f}",
                    )

                    # ---------------------------------------------------- #
                    print_header("TEST 3: Rescan produces no duplicates")
                    total_tests += 1
                    outcome2 = orchestrator.run_scan(include_auto_drives=False, persist_report=False)
                    duplicates = len(outcome2.projects_new)
                    results["duplicate_project_count"] = duplicates
                    ok = duplicates == 0 and len(outcome2.projects_existing) == 4
                    passed_tests += ok
                    print_result(
                        "Rescan re-detects existing without duplicating",
                        ok,
                        f"new={duplicates} existing={len(outcome2.projects_existing)}",
                    )
                finally:
                    db.close()
            finally:
                settings.workspace_roots = original["workspace_roots"]
                settings.auto_discover_drives = original["auto_discover_drives"]
                settings.project_scan_max_depth = original["max_depth"]
    except Exception as exc:  # pragma: no cover
        print_result("Detection evaluation", False, str(exc))

    # ---------------------------------------------------------------- #
    print_header("TEST 4: Zero-Memory Project Visibility")
    total_tests += 1
    try:
        db = TestSession()
        try:
            service = ProjectService(db)
            with tempfile.TemporaryDirectory() as tmpdir:
                p = Path(tmpdir) / "ghost-project"
                p.mkdir()
                (p / "package.json").write_text("{}")
                service.register_project(str(p))
                projects, counts, _total = service.list_projects_with_counts()
                ghost = [pr for pr in projects if pr.name == "ghost-project"]
                ok = bool(ghost) and counts.get(ghost[0].namespace, 0) == 0
                results["zero_memory_visibility_success_rate"] = 1.0 if ok else 0.0
                passed_tests += ok
                print_result(
                    "Zero-memory project appears in registry listing",
                    ok,
                    f"projects={[pr.name for pr in projects]}",
                )
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print_result("Zero-memory visibility", False, str(exc))

    # ---------------------------------------------------------------- #
    print_header("TEST 5: Ignored Projects Never Reappear")
    total_tests += 1
    try:
        db = TestSession()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                keep = root / "keeper"
                keep.mkdir()
                (keep / "pyproject.toml").write_text("")
                gone = root / "scratch-repo"
                make_git_repo(gone)

                settings = get_settings()
                saved = settings.workspace_roots
                settings.workspace_roots = str(root)
                try:
                    service = ProjectService(db)
                    first = service.run_workstation_scan(include_auto_drives=False)
                    scratch = next((p for p in first.projects_new if p.name == "scratch-repo"), None)
                    keeper_before = sum(1 for p in first.projects_new if p.name == "keeper")

                    service.set_ignored(scratch.id, True)

                    second = service.run_workstation_scan(include_auto_drives=False)
                    reappeared = [
                        p
                        for p in [*second.projects_new, *second.projects_existing]
                        if p.name == "scratch-repo"
                    ]
                    results["ignored_project_reappearance_count"] = len(reappeared)
                    keeper_after = sum(
                        1 for p in [*second.projects_new, *second.projects_existing] if p.name == "keeper"
                    )
                    ok = (
                        scratch is not None
                        and len(reappeared) == 0
                        and keeper_before == 1
                        and keeper_after == 1
                    )
                    passed_tests += ok
                    print_result(
                        "Ignored project excluded from rescan; others unaffected",
                        ok,
                        f"reappeared={len(reappeared)}",
                    )
                finally:
                    settings.workspace_roots = saved
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover
        print_result("Ignore behavior", False, str(exc))

    # ---------------------------------------------------------------- #
    print_header("TEST 6: Permission Errors Do Not Crash Scan")
    total_tests += 1
    try:
        real_scandir = os.scandir

        def flaky_scandir(path):
            key = str(path).lower()
            if key.endswith(("locked-dir", "locked-dir\\")):
                raise PermissionError(13, "Access denied", str(path))
            return real_scandir(path)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = root / "good-project"
            good.mkdir()
            (good / "Cargo.toml").write_text("")
            locked = root / "locked-dir"
            locked.mkdir()
            (locked / "secret.marker").write_text("")

            from app.projects.scanner import WorkspaceScanner

            with unittest.mock.patch("app.projects.scanner.os.scandir", side_effect=flaky_scandir):
                scanner = WorkspaceScanner(max_depth=4)
                result = scanner.scan_roots([str(root)])

            names = {d.name for d in result.detected}
            ok = names == {"good-project"} and result.stats.permission_errors >= 1
            results["permission_error_crash_count"] = 0
            passed_tests += ok
            print_result(
                "Unreadable directory tolerated, scan completed",
                ok,
                f"detected={sorted(names)} permission_errors={result.stats.permission_errors}",
            )
    except Exception as exc:  # pragma: no cover
        results["permission_error_crash_count"] = 1
        print_result("Permission error tolerance", False, str(exc))

    # ---------------------------------------------------------------- #
    print_header("EVALUATION SUMMARY")
    print(f"  Total tests:     {total_tests}")
    print(f"  Passed:          {passed_tests}")
    print(f"  Failed:          {total_tests - passed_tests}")
    print(f"  Success rate:    {passed_tests / total_tests * 100:.1f}%")

    print("\n  Discovery Metrics:")
    targets = {
        "drive_enumeration_accuracy": (1.0, "rate"),
        "project_detection_precision": (1.0, "rate"),
        "project_detection_recall": (1.0, "rate"),
        "zero_memory_visibility_success_rate": (1.0, "rate"),
        "duplicate_project_count": (0, "count"),
        "ignored_project_reappearance_count": (0, "count"),
        "permission_error_crash_count": (0, "count"),
    }
    all_ok = True
    for key, (target, kind) in targets.items():
        value = results[key]
        if kind == "rate":
            ok = value >= target
        else:
            ok = value == target
        all_ok = all_ok and ok
        print(f"    {key}: {value} (target={target}) [{'OK' if ok else 'VIOLATION'}]")

    stamp = datetime.now(UTC).isoformat()
    print(f"\n  All targets met: {'YES' if all_ok else 'NO'}  ({stamp})")
    return 0 if (passed_tests == total_tests and all_ok) else 1


if __name__ == "__main__":
    sys.exit(run_evaluation())
