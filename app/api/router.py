"""API router aggregation."""

from fastapi import APIRouter

from app.api import admission, events, memories

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(events.router)
api_router.include_router(memories.router)
api_router.include_router(admission.router)
