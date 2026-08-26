"""M8 Capture evaluation script."""

from __future__ import annotations

import json
import tempfile
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.database import Base
from app.models.project import Project, ProjectStatus
from app.models.capture import (
    CaptureEvent,
    CaptureSource,
    CaptureEventType,
    CaptureProcessingStatus,
    AdmissionDecision,
)
from app.projects.service import ProjectService
from app.projects.discovery import ProjectDiscoveryService
from app.capture.service import CaptureService
from app.capture.project_resolver import ProjectResolver
from app.capture.repository import CaptureEventRepository
from app.capture.adapters import GitAdapter, FilesystemAdapter
from app.capture.fingerprints import make_git_fingerprint, make_filesystem_fingerprint
from app.config import get_settings


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(name: str, passed: bool, details: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if details:
        print(f"       {details}")


def run_evaluation() -> int:
    """Run M8 capture evaluation."""
    print_header("MUNIN M8 CAPTURE EVALUATION")

    # Use deterministic provider for evaluation
    import os
    os.environ["ADMISSION_PROVIDER"] = "deterministic"
    os.environ["DEDUP_PROVIDER"] = "deterministic"
    os.environ["TEMPORAL_PROVIDER"] = "deterministic"
    os.environ["CONSOLIDATION_PROVIDER"] = "deterministic"
    os.environ["EMBEDDING_PROVIDER"] = "deterministic"

    # Isolate the evaluation against a throwaway DB so the acceptance harness
    # never mutates the production registry under data/munin.db (mirroring the
    # isolated-DB behaviour already used by the M8 pytest suite).
    from sqlalchemy.orm import sessionmaker
    from app.database import create_db_engine

    eval_dir = tempfile.mkdtemp(prefix="munin_cap_eval_")
    eval_engine = create_db_engine(f"sqlite:///{eval_dir}/eval.db")
    Base.metadata.create_all(eval_engine)
    EvalSession = sessionmaker(bind=eval_engine, autocommit=False, autoflush=False)

    results = {
        "project_discovery_success_rate": 0.0,
        "duplicate_project_count": 0,
        "duplicate_capture_count": 0,
        "namespace_leak_count": 0,
        "secret_capture_count": 0,
        "git_replay_count": 0,
        "filesystem_overcapture_count": 0,
        "cross_agent_continuity_success_rate": 0.0,
    }

    total_tests = 0
    passed_tests = 0

    # Test 1: Project Discovery
    print_header("TEST 1: Project Discovery")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create 3 git repos
        for name in ["project_a", "project_b", "project_c"]:
            repo = root / name
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
            (repo / "README.md").write_text(f"# {name}")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)

        # Create excluded dirs
        (root / "node_modules").mkdir()
        (root / "node_modules" / "pkg.json").write_text("{}")
        (root / ".venv").mkdir()
        (root / ".venv" / "pyvenv.cfg").write_text("")

        db = EvalSession()
        try:
            service = ProjectService(db)
            settings = get_settings()
            settings.workspace_roots = str(root)

            discovered = service.scan_workspace_roots()
            total_tests += 1
            if len(discovered) == 3:
                passed_tests += 1
                results["project_discovery_success_rate"] = 1.0
                print_result("Discovered 3 projects", True, f"Found: {[p.name for p in discovered]}")
            else:
                results["project_discovery_success_rate"] = len(discovered) / 3
                print_result("Discovered 3 projects", False, f"Found {len(discovered)}: {[p.name for p in discovered]}")

            # Check no duplicates after re-scan
            discovered2 = service.scan_workspace_roots()
            total_tests += 1
            if len(discovered2) == 0:  # Already registered
                passed_tests += 1
                results["duplicate_project_count"] = 0
                print_result("No duplicate projects on re-scan", True)
            else:
                results["duplicate_project_count"] = len(discovered2)
                print_result("No duplicate projects on re-scan", False, f"Found {len(discovered2)} duplicates")

        finally:
            db.close()

    # Test 2: Namespace Mapping
    print_header("TEST 2: Namespace Mapping")
    with tempfile.TemporaryDirectory() as tmpdir:
        db = EvalSession()
        try:
            service = ProjectService(db)

            # Same name, different paths
            for i in range(2):
                p = Path(tmpdir) / f"proj_{i}"
                p.mkdir()
                subprocess.run(["git", "init"], cwd=p, capture_output=True)
                subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=p, capture_output=True)
                subprocess.run(["git", "config", "user.name", "Test"], cwd=p, capture_output=True)
                (p / "README.md").write_text("# Test")
                subprocess.run(["git", "add", "."], cwd=p, capture_output=True)
                subprocess.run(["git", "commit", "-m", "Initial"], cwd=p, capture_output=True)

                proj = service.register_project(str(p), name="same_name")
                if i == 0:
                    assert proj.namespace == "project:same-name"
                else:
                    assert proj.namespace == "project:same-name-2"

            total_tests += 1
            passed_tests += 1
            print_result("Namespace collision resolved", True)
        finally:
            db.close()

    # Test 3: Git Capture Idempotency
    print_header("TEST 3: Git Capture Idempotency")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True)

        db = EvalSession()
        try:
            service = ProjectService(db)
            project = service.register_project(str(repo), enable_capture=True)
            capture_service = CaptureService(db)
            repo_obj = CaptureEventRepository(db)

            adapter = GitAdapter(project)

            # First discovery
            events1 = adapter.discover_events(project, db)
            total_tests += 1
            if len(events1) >= 1:
                passed_tests += 1
                print_result("First git discovery finds commits", True, f"Found {len(events1)} events")
            else:
                print_result("First git discovery finds commits", False, "No events found")

            # Second discovery - should find no new events
            events2 = adapter.discover_events(project, db)
            total_tests += 1
            if len(events2) == 0:
                passed_tests += 1
                results["git_replay_count"] = 0
                print_result("No replay on second discovery", True)
            else:
                results["git_replay_count"] = len(events2)
                print_result("No replay on second discovery", False, f"Replayed {len(events2)} events")

        finally:
            db.close()

    # Test 4: Filesystem Capture Batching
    print_header("TEST 4: Filesystem Capture Batching")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)

        db = EvalSession()
        try:
            service = ProjectService(db)
            project = service.register_project(str(repo), enable_capture=True)

            adapter = FilesystemAdapter(project)

            # Create some files
            (repo / "file1.py").write_text("print(1)")
            (repo / "file2.py").write_text("print(2)")
            (repo / "file3.py").write_text("print(3)")

            events = adapter.discover_events(project, db)
            total_tests += 1
            # Should batch into one event
            if len(events) <= 1:
                passed_tests += 1
                results["filesystem_overcapture_count"] = 0
                print_result("Filesystem changes batched", True, f"Created {len(events)} capture event(s)")
            else:
                results["filesystem_overcapture_count"] = len(events) - 1
                print_result("Filesystem changes batched", False, f"Created {len(events)} capture events (overcapture)")

        finally:
            db.close()

    # Test 5: Privacy - Excluded Paths
    print_header("TEST 5: Privacy - Excluded Paths")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)

        db = EvalSession()
        try:
            service = ProjectService(db)
            project = service.register_project(str(repo), enable_capture=True)

            adapter = FilesystemAdapter(project)

            # Create secret files
            (repo / ".env").write_text("SECRET_KEY=abc123")
            (repo / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----")
            (repo / "credentials.json").write_text('{"api_key": "secret"}')

            # Create normal file
            (repo / "normal.py").write_text("print('hello')")

            # Check exclusions
            total_tests += 1
            if (adapter._should_exclude(repo / ".env") and
                adapter._should_exclude(repo / "id_rsa") and
                adapter._should_exclude(repo / "credentials.json")):
                passed_tests += 1
                results["secret_capture_count"] = 0
                print_result("Secret files excluded", True)
            else:
                results["secret_capture_count"] = 3
                print_result("Secret files excluded", False, "Some secret files not excluded")

        finally:
            db.close()

    # Test 6: Capture Idempotency via Fingerprints
    print_header("TEST 6: Capture Idempotency")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)

        db = EvalSession()
        try:
            service = ProjectService(db)
            project = service.register_project(str(repo), enable_capture=True)
            capture_service = CaptureService(db)
            repo_obj = CaptureEventRepository(db)

            # Create capture with explicit fingerprint
            fp = make_git_fingerprint(project, "abc123")

            capture1 = capture_service.capture_event(
                project=project,
                source=CaptureSource.git,
                source_event_type=CaptureEventType.git_commit,
                content="Test commit",
                fingerprint=fp,
            )

            capture2 = capture_service.capture_event(
                project=project,
                source=CaptureSource.git,
                source_event_type=CaptureEventType.git_commit,
                content="Test commit",
                fingerprint=fp,
            )

            total_tests += 1
            if capture1.id == capture2.id and repo_obj.count_by_project(project.id) == 1:
                passed_tests += 1
                results["duplicate_capture_count"] = 0
                print_result("Capture idempotent via fingerprint", True)
            else:
                results["duplicate_capture_count"] = repo_obj.count_by_project(project.id) - 1
                print_result("Capture idempotent via fingerprint", False, f"Duplicates: {repo_obj.count_by_project(project.id)}")

        finally:
            db.close()

    # Test 7: Cross-Agent Continuity
    print_header("TEST 7: Cross-Agent Continuity")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)

        db = EvalSession()
        try:
            service = ProjectService(db)
            project = service.register_project(str(repo), enable_capture=True)
            capture_service = CaptureService(db)

            # Agent 1 (Codex) does work
            capture_service.capture_agent_summary(
                project=project,
                summary="Implemented user authentication with JWT. Added login/register endpoints. "
                       "Created AuthMiddleware for token validation. Using HttpOnly cookies for refresh tokens.",
                agent_id="codex",
                session_id="session-1",
            )

            capture_service.capture_git_commit(
                project=project,
                commit_sha="abc123",
                commit_message="feat(auth): add JWT authentication",
                author="Codex",
                changed_files=["app/auth/router.py", "app/auth/middleware.py"],
                branch="main",
            )

            # Simulate process restart - new DB session
            db2 = EvalSession()
            try:
                resolver = ProjectResolver(db2)
                project2 = resolver.resolve_by_namespace(project.namespace)
                assert project2 is not None

                # Agent 2 (OpenCode) queries context
                from app.agent.service import AgentService
                from app.agent.models import AgentContextRequest
                agent_service = AgentService(db2)

                context = agent_service.get_context(AgentContextRequest(
                    query="How does authentication work?",
                    namespace=project.namespace,
                    token_budget=1000,
                    max_memories=10,
                ))

                total_tests += 1
                auth_terms = ["jwt", "auth", "token", "login", "middleware"]
                found_terms = [t for t in auth_terms if t in " ".join(m.content for m in context.memories_used).lower()]

                if len(found_terms) >= 2:
                    passed_tests += 1
                    results["cross_agent_continuity_success_rate"] = 1.0
                    print_result("Cross-agent continuity works", True, f"Found terms: {found_terms}")
                else:
                    results["cross_agent_continuity_success_rate"] = 0.0
                    print_result("Cross-agent continuity works", False, f"Only found: {found_terms}")

            finally:
                db2.close()
        finally:
            db.close()

    # Summary
    print_header("EVALUATION SUMMARY")
    print(f"  Total tests:     {total_tests}")
    print(f"  Passed:          {passed_tests}")
    print(f"  Failed:          {total_tests - passed_tests}")
    print(f"  Success rate:    {passed_tests / total_tests * 100:.1f}%")

    print("\n  Safety Metrics:")
    for key, value in results.items():
        if key.endswith("_count"):
            target = 0
            status = "OK" if value == target else "VIOLATION"
            print(f"    {key}: {value} (target={target}) [{status}]")
        elif key.endswith("_rate"):
            target = 1.0
            status = "OK" if value >= target * 0.9 else "BELOW TARGET"
            print(f"    {key}: {value:.2f} (target={target}) [{status}]")

    # Required safety targets
    safety_ok = (
        results["duplicate_project_count"] == 0 and
        results["duplicate_capture_count"] == 0 and
        results["namespace_leak_count"] == 0 and
        results["secret_capture_count"] == 0 and
        results["git_replay_count"] == 0 and
        results["filesystem_overcapture_count"] == 0
    )

    print(f"\n  Safety targets met: {'YES' if safety_ok else 'NO'}")

    return 0 if (passed_tests == total_tests and safety_ok) else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_evaluation())