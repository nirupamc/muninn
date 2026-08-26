"""Regression tests: push-based capture adapters must never be background-polled.

M8.1: live startup previously logged

    GenericCaptureBridge.discover_events() takes 1 positional argument
    but 3 were given

because CaptureManager polled the push-based GenericCaptureBridge like a
polling adapter. The intended architecture is:

    GitAdapter           -> background/polling   (supports_polling = True)
    FilesystemAdapter    -> background/polling   (supports_polling = True)
    GenericCaptureBridge -> PUSH-BASED ONLY      (supports_polling = False)
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.capture.adapters.base import CaptureAdapter
from app.capture.adapters.filesystem import FilesystemAdapter
from app.capture.adapters.generic import GenericCaptureBridge
from app.capture.adapters.git import GitAdapter
from app.capture.manager import CaptureManager
from app.database import Base
from app.models.project import Project, ProjectStatus


_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def setup_module() -> None:
    Base.metadata.create_all(_engine)


def _make_project() -> Project:
    return Project(
        id="poll-test-project",
        name="demo",
        namespace="project:demo",
        root_path=r"E:\tmp\demo",
        canonical_path="e:/tmp/demo",
        status=ProjectStatus.connected,
        capture_enabled=True,
    )


def test_adapter_polling_flags() -> None:
    """Polling vs push-based adapter classification is explicit."""
    project = _make_project()
    assert GitAdapter(project).supports_polling is True
    assert FilesystemAdapter(project).supports_polling is True
    assert GenericCaptureBridge(project).supports_polling is False
    # Polling remains the default for future polling adapters.
    assert CaptureAdapter.supports_polling is True


def test_manager_creates_bridge_for_health_but_never_polls_it() -> None:
    """_process_project must skip push-based adapters entirely."""
    Base.metadata.create_all(_engine)
    project = _make_project()
    manager = CaptureManager(lambda: None)
    manager._adapters[project.id] = [
        GitAdapter(project),
        FilesystemAdapter(project),
        GenericCaptureBridge(project),
    ]

    polled: list[str] = []

    class SpyPolling(GitAdapter):
        def discover_events(self, proj, db):  # noqa: ANN001 - test spy signature
            polled.append(self.name.value)
            return []

    class SpyBridge(GenericCaptureBridge):
        def discover_events(self, *args, **kwargs):  # noqa: ANN002/ANN003
            polled.append(self.name.value)
            return []

    manager._adapters[project.id] = [SpyPolling(project), SpyBridge(project)]
    db = SessionLocal()
    try:
        asyncio.run(manager._process_project(project, service=None, db=db))
    finally:
        db.close()

    assert "git" in polled, "polling adapter should have been polled"
    assert "generic" not in polled, (
        "push-based GenericCaptureBridge must NOT be polled by CaptureManager"
    )


def test_bridge_discover_events_is_zero_arg_safe() -> None:
    """The bridge's own contract stays push-only and argument-free."""
    bridge = GenericCaptureBridge(_make_project())
    assert bridge.discover_events() == []
