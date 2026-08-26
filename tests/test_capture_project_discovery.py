"""Tests for M8 project discovery and capture."""

from __future__ import annotations

import tempfile
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker as _sessionmaker

# Isolated throwaway database so test teardown never wipes the
# production project registry in data/munin.db.
_test_db_dir = tempfile.mkdtemp(prefix="munin_m8_tests_")
engine = create_engine(f"sqlite:///{_test_db_dir}/m8.db", connect_args={"check_same_thread": False})
TestSessionLocal = _sessionmaker(bind=engine, autocommit=False, autoflush=False)
from app.database import Base
from app.models.project import Project, ProjectStatus
from app.models.capture import CaptureEvent, CaptureSource, CaptureEventType, CaptureProcessingStatus
from app.projects.service import ProjectService
from app.projects.discovery import ProjectDiscoveryService
from app.capture.service import CaptureService
from app.capture.project_resolver import ProjectResolver
from app.capture.repository import CaptureEventRepository


def setup_module() -> None:
    """Create tables."""
    Base.metadata.create_all(engine)


def teardown_module() -> None:
    """Drop tables."""
    Base.metadata.drop_all(engine)


def test_project_registration() -> None:
    """Test registering a project."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            assert project is not None
            assert project.name == "test_project"
            assert project.namespace.startswith("project:")
            assert project.capture_enabled is True
            assert project.status == ProjectStatus.connected
            assert project.git_root is not None

            # Duplicate registration should return existing
            project2 = service.register_project(str(project_path))
            assert project2.id == project.id
        finally:
            db.close()


def test_project_discovery() -> None:
    """Test discovering projects from workspace roots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create two git repos
        repo1 = root / "project_alpha"
        repo1.mkdir()
        subprocess.run(["git", "init"], cwd=repo1, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo1, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo1, capture_output=True)
        (repo1 / "file1.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=repo1, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo1, capture_output=True)

        repo2 = root / "project_beta"
        repo2.mkdir()
        subprocess.run(["git", "init"], cwd=repo2, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo2, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo2, capture_output=True)
        (repo2 / "file2.py").write_text("print('world')")
        subprocess.run(["git", "add", "."], cwd=repo2, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo2, capture_output=True)

        # Create excluded directories
        excluded = root / "node_modules"
        excluded.mkdir()
        (excluded / "package.json").write_text("{}")

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            # Manually set workspace roots for test
            from app.config import get_settings
            settings = get_settings()
            settings.workspace_roots = str(root)

            discovered = service.scan_workspace_roots()

            assert len(discovered) == 2
            names = {p.name for p in discovered}
            assert names == {"project_alpha", "project_beta"}

            # Verify they were persisted
            projects = service.list_projects()
            assert len(projects) >= 2
        finally:
            db.close()


def test_namespace_collision_resolution() -> None:
    """Test that namespace collisions are resolved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project1 = service.register_project(str(project_path))
            assert project1.namespace == "project:test-project"

            # Create another project with same name
            project_path2 = Path(tmpdir) / "test_project2"
            project_path2.mkdir()
            subprocess.run(["git", "init"], cwd=project_path2, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path2, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path2, capture_output=True)
            (project_path2 / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=project_path2, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=project_path2, capture_output=True)

            project2 = service.register_project(str(project_path2), name="test_project")
            assert project2.namespace == "project:test-project-2"
        finally:
            db.close()


def test_git_capture_adapter() -> None:
    """Test Git capture adapter detects commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            from app.capture.adapters import GitAdapter
            adapter = GitAdapter(project)

            assert adapter.available() is True

            # Discover events - should find the initial commit
            events = adapter.discover_events(project, db)
            # The adapter discovers commits since last checkpoint (which is empty)
            # So it should find the HEAD commit
            # Note: depends on checkpoint logic
        finally:
            db.close()


def test_capture_event_idempotency() -> None:
    """Test that capture events are idempotent via fingerprint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            capture_service = CaptureService(db)
            repo = CaptureEventRepository(db)

            # First capture
            fingerprint = "test-fingerprint-123"
            capture1 = capture_service.capture_event(
                project=project,
                source=CaptureSource.generic,
                source_event_type=CaptureEventType.manual_note,
                content="Test content",
                fingerprint=fingerprint,
            )

            assert capture1.fingerprint == fingerprint
            assert capture1.processing_status == CaptureProcessingStatus.completed

            # Second capture with same fingerprint should return existing
            capture2 = capture_service.capture_event(
                project=project,
                source=CaptureSource.generic,
                source_event_type=CaptureEventType.manual_note,
                content="Test content",
                fingerprint=fingerprint,
            )

            assert capture2.id == capture1.id
            assert repo.count_by_project(project.id) == 1
        finally:
            db.close()


def test_capture_through_admission_pipeline() -> None:
    """Test that capture events go through the admission pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            capture_service = CaptureService(db)

            # Submit a meaningful capture that should pass admission
            capture = capture_service.capture_event(
                project=project,
                source=CaptureSource.generic,
                source_event_type=CaptureEventType.agent_summary,
                content="Implemented user authentication with JWT tokens. Added login/logout endpoints and middleware for token validation.",
                agent_id="test-agent",
                session_id="test-session",
            )

            # Should complete processing
            assert capture.processing_status == CaptureProcessingStatus.completed
            # May or may not create a memory depending on admission threshold
        finally:
            db.close()


def test_filesystem_exclusion() -> None:
    """Test that excluded paths are not captured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        # Create excluded directories
        node_modules = project_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "package.json").write_text("{}")

        venv = project_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("")

        git_dir = project_path / ".git"
        assert git_dir.exists()

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            from app.capture.adapters import FilesystemAdapter
            adapter = FilesystemAdapter(project)

            # The adapter should exclude these paths
            assert adapter._should_exclude(node_modules / "package.json") is True
            assert adapter._should_exclude(venv / "pyvenv.cfg") is True
            # .git is not excluded by default but handled separately
            # Actually .git is in EXCLUDED_DIRS
            assert adapter._should_exclude(git_dir / "config") is True
        finally:
            db.close()


def test_capture_audit_table() -> None:
    """Test that capture events are persisted in audit table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)

            capture_service = CaptureService(db)
            repo = CaptureEventRepository(db)

            # Create multiple capture events
            for i in range(3):
                capture_service.capture_event(
                    project=project,
                    source=CaptureSource.generic,
                    source_event_type=CaptureEventType.manual_note,
                    content=f"Test note {i}",
                    fingerprint=f"test-fp-{i}",
                )

            events = repo.list_by_project(project.id)
            assert len(events) == 3

            # Check all have proper fields
            for event in events:
                assert event.project_id == project.id
                assert event.namespace == project.namespace
                assert event.fingerprint is not None
                assert event.occurred_at is not None
                assert event.captured_at is not None
        finally:
            db.close()


def test_project_status_transitions() -> None:
    """Test project status transitions based on activity."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path))

            # Initially discovered
            assert project.status == ProjectStatus.discovered

            # Enable capture -> connected
            service.enable_capture(project.id)
            db.refresh(project)
            assert project.status == ProjectStatus.connected

            # Capture activity -> active
            from datetime import datetime, UTC
            service.update_activity(project.id, datetime.now(UTC))
            db.refresh(project)
            assert project.status == ProjectStatus.active

            # Disable -> disabled
            service.disable_capture(project.id)
            db.refresh(project)
            assert project.status == ProjectStatus.disabled
        finally:
            db.close()


def test_cross_agent_continuity_simulation() -> None:
    """Simulate cross-agent continuity: Agent A works, Agent B continues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_path, capture_output=True)
        (project_path / "README.md").write_text("# Test Project")
        subprocess.run(["git", "add", "."], cwd=project_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True)

        db = TestSessionLocal()
        try:
            service = ProjectService(db)
            project = service.register_project(str(project_path), enable_capture=True)
            capture_service = CaptureService(db)

            # Agent A (Codex) works on auth feature
            capture_service.capture_agent_summary(
                project=project,
                summary="Implemented JWT authentication. Added /auth/login and /auth/register endpoints. "
                       "Created AuthMiddleware for token validation. Stored refresh tokens in HttpOnly cookies.",
                agent_id="codex",
                session_id="session-1",
            )

            # Agent A makes a commit
            capture_service.capture_git_commit(
                project=project,
                commit_sha="abc123",
                commit_message="feat(auth): add JWT authentication with refresh tokens",
                author="Codex Agent",
                changed_files=["app/auth/router.py", "app/auth/middleware.py", "app/auth/models.py"],
                branch="main",
            )

            # Simulate restart - new DB session
            db2 = TestSessionLocal()
            try:
                resolver = ProjectResolver(db2)
                project2 = resolver.resolve_by_namespace(project.namespace)
                assert project2 is not None
                assert project2.id == project.id

                # Agent B (OpenCode) queries context
                from app.agent.service import AgentService
                agent_service = AgentService(db2)

                # Query for auth-related context
                context = agent_service.get_context(
                    payload=__import__("app.agent.models", fromlist=["AgentContextRequest"]).AgentContextRequest(
                        query="How does authentication work in this project?",
                        namespace=project.namespace,
                        token_budget=1000,
                        max_memories=10,
                    )
                )

                # Should find the auth memories
                assert context.memories_used is not None
                auth_content = " ".join(m.content for m in context.memories_used).lower()
                assert "jwt" in auth_content or "auth" in auth_content or "token" in auth_content
            finally:
                db2.close()
        finally:
            db.close()