"""Munin FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.config import get_settings

logger = logging.getLogger("munin")


def configure_logging(level: str) -> None:
    """Configure application logging without dumping private content."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Munin starting (env=%s, version=%s)", settings.munin_env, __version__)
    logger.info("database configured")
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

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "munin"}

    return application


app = create_app()
