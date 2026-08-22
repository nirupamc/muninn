"""API router aggregation."""

from fastapi import APIRouter

from app.api import admission, agent, consolidation, context, events, memories

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(events.router)
api_router.include_router(memories.router)
api_router.include_router(admission.router)
api_router.include_router(context.router)
# Consolidation routes share /memories prefix — must come after memories.router
# so specific paths (/consolidate, /consolidate/preview) take precedence.
api_router.include_router(consolidation.router)
# M7A agent-facing endpoints.
api_router.include_router(agent.router)
