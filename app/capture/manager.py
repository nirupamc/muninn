"""Capture manager for background capture processing."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.capture.adapters import (
    CaptureAdapter,
    FilesystemAdapter,
    GenericCaptureBridge,
    GitAdapter,
)
from app.capture.project_resolver import ProjectResolver
from app.capture.service import CaptureService
from app.models.project import Project
from app.projects.repository import ProjectRepository

logger = logging.getLogger("munin.capture.manager")


class CaptureManager:
    """Manages background capture for all enabled projects."""

    def __init__(self, db_factory: callable) -> None:
        self.db_factory = db_factory
        self._adapters: dict[str, list[CaptureAdapter]] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def _create_adapters(self, project: Project, db: Session) -> list[CaptureAdapter]:
        """Create adapters for a project."""
        adapters = []
        from app.config import get_settings
        s = get_settings()

        if s.capture_git_enabled:
            adapters.append(GitAdapter(project))
        if s.capture_filesystem_enabled:
            adapters.append(FilesystemAdapter(project))
        # Generic bridge is always available for API submissions
        adapters.append(GenericCaptureBridge(project))
        return adapters

    async def start(self) -> None:
        """Start the capture manager."""
        if self._running:
            return

        self._running = True
        logger.info("Starting capture manager")

        # Initial scan of projects
        await self._refresh_projects()

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._capture_loop()),
            asyncio.create_task(self._health_check_loop()),
        ]

    async def stop(self) -> None:
        """Stop the capture manager."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping capture manager")

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _refresh_projects(self) -> None:
        """Refresh the list of projects and their adapters."""
        db = self.db_factory()
        try:
            repo = ProjectRepository(db)
            projects = repo.list_all(capture_enabled=True, limit=1000)

            for project in projects:
                self._adapters[project.id] = self._create_adapters(project, db)

            logger.info("Capture manager tracking %d projects", len(self._adapters))
        finally:
            db.close()

    async def _capture_loop(self) -> None:
        """Main capture loop."""
        while self._running:
            try:
                await self._process_all_projects()
            except Exception as e:
                logger.error("Error in capture loop: %s", e)
            await asyncio.sleep(30)  # Check every 30 seconds

    async def _process_all_projects(self) -> None:
        """Process all projects with capture enabled."""
        db = self.db_factory()
        try:
            resolver = ProjectResolver(db)
            service = CaptureService(db)

            projects = resolver.get_active_projects()
            for project in projects:
                try:
                    await self._process_project(project, service, db)
                    db.commit()  # Commit after each project to persist checkpoints
                except Exception as e:
                    db.rollback()
                    logger.error("Error processing project %s: %s", project.id, e)
        finally:
            db.close()

    async def _process_project(self, project: Project, service: CaptureService, db: Session) -> None:
        """Process a single project's adapters."""
        adapters = self._adapters.get(project.id, [])
        for adapter in adapters:
            try:
                events = adapter.discover_events(project, db)
                for event_data in events:
                    await self._process_event(project, service, db, adapter, event_data)
            except Exception as e:
                logger.error("Error with adapter %s for project %s: %s", adapter.name, project.id, e)

    async def _process_event(
        self,
        project: Project,
        service: CaptureService,
        db: Session,
        adapter: CaptureAdapter,
        event_data: dict[str, Any],
    ) -> None:
        """Process a single capture event."""
        from app.models.capture import CaptureEventType, CaptureSource

        event_type = event_data.get("event_type")
        if isinstance(event_type, str):
            event_type = CaptureEventType(event_type)

        content = event_data.get("content", "")
        metadata = event_data.get("metadata", {})
        occurred_at = event_data.get("occurred_at", datetime.now(UTC))
        agent_id = event_data.get("agent_id")
        session_id = event_data.get("session_id")
        working_directory = event_data.get("working_directory")
        fingerprint = event_data.get("fingerprint")

        service.capture_event(
            project=project,
            source=adapter.name,
            source_event_type=event_type,
            content=content,
            agent_id=agent_id,
            session_id=session_id,
            working_directory=working_directory,
            metadata=metadata,
            occurred_at=occurred_at,
            fingerprint=fingerprint,
        )

        adapter.checkpoint(project, db, event_data)
        logger.info("Processed capture event for project %s: %s", project.id, event_type)

    async def _health_check_loop(self) -> None:
        """Periodic health check and adapter refresh."""
        while self._running:
            await asyncio.sleep(300)  # Every 5 minutes
            try:
                await self._refresh_projects()
            except Exception as e:
                logger.error("Error in health check: %s", e)

    def get_adapter_health(self, project_id: str) -> list[dict[str, Any]]:
        """Get health status for all adapters of a project."""
        adapters = self._adapters.get(project_id, [])
        return [adapter.health().__dict__ for adapter in adapters]


# Global manager instance
_capture_manager: CaptureManager | None = None


def get_capture_manager() -> CaptureManager | None:
    """Get the global capture manager instance."""
    return _capture_manager


def set_capture_manager(manager: CaptureManager) -> None:
    """Set the global capture manager instance."""
    global _capture_manager
    _capture_manager = manager


@asynccontextmanager
async def capture_lifespan(db_factory: callable):
    """FastAPI lifespan for capture manager."""
    global _capture_manager
    manager = CaptureManager(db_factory)
    set_capture_manager(manager)
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()
        set_capture_manager(None)