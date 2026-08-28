"""Munin FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.projects import router as projects_router
from app.api.capture import router as capture_router
from app.api.router import api_router
from app.capture.manager import CaptureManager, set_capture_manager
from app.config import get_settings
from app.database import SessionLocal

logger = logging.getLogger("munin")


def configure_logging(level: str) -> None:
    """Configure application logging without dumping private content."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _db_factory() -> SessionLocal:
    return SessionLocal()


async def _optional_background_discovery() -> None:
    """Optional, non-blocking discovery scan after API readiness."""
    import asyncio

    from app.projects.discovery import ProjectDiscoveryService, SCAN_STATUS

    try:
        def _run() -> None:
            db = SessionLocal()
            try:
                ProjectDiscoveryService(db).run_scan()
                db.commit()
            except Exception as exc:  # pragma: no cover - background safety
                logger.warning("Background project discovery failed: %s", exc)
            finally:
                db.close()

        await asyncio.to_thread(_run)
        logger.info("background project discovery complete (in_progress=%s)", SCAN_STATUS.snapshot()["scan_in_progress"])
    except Exception as exc:  # pragma: no cover - background safety
        logger.warning("Background project discovery could not start: %s", exc)


async def _agent_session_capture_loop() -> None:
    """Background task for agent session capture (M8.3)."""
    import asyncio
    from app.capture.agent_sessions.service import AgentSessionService
    from app.config import get_settings

    settings = get_settings()
    poll_interval = getattr(settings, "agent_session_poll_seconds", 60)

    # Yield control once so Uvicorn can finish binding the port.
    await asyncio.sleep(0)
    while True:
        try:
            # Run the blocking session scan + processing in a thread so
            # the event loop stays free for HTTP serving.
            def _poll() -> tuple:
                db = SessionLocal()
                try:
                    service = AgentSessionService(db)
                    sessions = service.discover_sessions()
                    total_events = 0
                    total_captures = 0
                    total_memories = 0
                    for sess in sessions:
                        try:
                            result = service.process_session(sess)
                            total_events += result.events_discovered
                            total_captures += result.capture_events_created
                            total_memories += result.memories_created
                            if result.capture_events_created > 0 or result.memories_created > 0:
                                logger.info(
                                    "Agent session %s: %d events -> %d captures -> %d memories",
                                    sess.external_session_id[:16],
                                    result.events_discovered,
                                    result.capture_events_created,
                                    result.memories_created,
                                )
                            if result.errors:
                                logger.warning("Agent session %s: %d errors", sess.external_session_id[:16], len(result.errors))
                        except Exception as e:
                            logger.error("Error processing session %s: %s", sess.external_session_id[:16], e)
                    db.commit()
                    return len(sessions), total_events, total_captures, total_memories
                finally:
                    db.close()

            session_count, total_events, total_captures, total_memories = await asyncio.to_thread(_poll)
            if session_count > 0:
                logger.info(
                    "Agent session poll: discovered %d sessions, events=%d captures=%d memories=%d",
                    session_count, total_events, total_captures, total_memories,
                )
        except Exception as exc:
            logger.error("Agent session capture loop error: %s", exc)
        await asyncio.sleep(poll_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown.

    The capture manager is started inline (no nested @asynccontextmanager)
    and its background work runs via asyncio.to_thread so the event loop
    remains free for HTTP serving.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Munin starting (env=%s, version=%s)", settings.munin_env, __version__)
    from app.database import Base, engine

    Base.metadata.create_all(engine)
    logger.info("database configured")

    # Start capture manager — inline (no nested @asynccontextmanager)
    import asyncio
    _background_tasks = []

    manager = CaptureManager(_db_factory)
    set_capture_manager(manager)
    await manager.start()

    if settings.project_scan_on_start:
        asyncio.create_task(_optional_background_discovery())
        logger.info("background project discovery scheduled (non-blocking)")

    # Start agent session capture background task (M8.3)
    if getattr(settings, "agent_session_capture_enabled", True):
        task = asyncio.create_task(_agent_session_capture_loop())
        _background_tasks.append(task)
        logger.info("agent session capture background task started (poll every %d seconds)",
                   getattr(settings, "agent_session_poll_seconds", 60))

    logger.info("API ready")
    yield

    # Shutdown: cancel background tasks, stop capture manager
    for task in _background_tasks:
        task.cancel()
    await manager.stop()
    set_capture_manager(None)
    logger.info("Munin shutting down")


def create_app() -> FastAPI:
    """Application factory."""
    application = FastAPI(
        title="Munin",
        description="Standalone, local-first long-term memory layer for AI agents",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(api_router)
    application.include_router(projects_router, prefix="/api/v1")
    application.include_router(capture_router, prefix="/api/v1")
    application.include_router(projects_router)
    application.include_router(capture_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "munin"}

    return application


app = create_app()
