"""Munin FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.projects import router as projects_router
from app.api.capture import router as capture_router
from app.api.router import api_router
from app.capture.manager import capture_lifespan
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Munin starting (env=%s, version=%s)", settings.munin_env, __version__)
    # Local-first: ensure schema exists on startup (idempotent).
    from app.database import Base, engine

    Base.metadata.create_all(engine)
    logger.info("database configured")

    # Start capture manager
    async with capture_lifespan(_db_factory):
        logger.info("API ready")
        yield

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
    application.include_router(projects_router)
    application.include_router(capture_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "munin"}

    return application


app = create_app()
