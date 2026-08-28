"""M13 — Memory debugger read-only API endpoints.

All endpoints are strictly read-only. No memory mutations,
no reinforcement, no checkpoint advances, no side effects.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.debug.schemas import DebugMemoryView, DebugObservationView, DebugTimelineEntry
from app.debug.service import DebugService

router = APIRouter(prefix="/debug", tags=["debug"])


def get_debug_service(db: Session = Depends(get_db)) -> DebugService:
    return DebugService(db)


@router.get("/memories/{memory_id}", response_model=DebugMemoryView)
def debug_memory(
    memory_id: str,
    service: DebugService = Depends(get_debug_service),
) -> DebugMemoryView:
    """Complete debug view for one memory.

    Returns all traceable information: identity, representations,
    provenance, admission, dedup, reinforcement, temporal, and
    source events. Missing sections return null/empty safely.
    """
    view = service.get_memory_debug(memory_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found",
        )
    return view


@router.get("/observations/{capture_event_id}", response_model=DebugObservationView)
def debug_observation(
    capture_event_id: str,
    service: DebugService = Depends(get_debug_service),
) -> DebugObservationView:
    """Debug view for one capture event / observation.

    Shows source, observation type, filter result, admission decision,
    and memory outcome. Especially useful when no memory was created.
    """
    view = service.get_observation_debug(capture_event_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capture event '{capture_event_id}' not found",
        )
    return view


@router.get("/timeline", response_model=list[DebugTimelineEntry])
def debug_timeline(
    namespace: str | None = Query(default=None, description="Filter by namespace"),
    limit: int = Query(default=50, ge=1, le=100, description="Max entries"),
    service: DebugService = Depends(get_debug_service),
) -> list[DebugTimelineEntry]:
    """Bounded recent debug timeline.

    Derives timeline entries from persisted capture_events and
    admissions. No new records are created.
    """
    return service.get_recent_timeline(namespace=namespace, limit=limit)
