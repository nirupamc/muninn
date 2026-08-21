"""Consolidation HTTP endpoints.

POST /api/v1/memories/consolidate          — consolidate memories
POST /api/v1/memories/consolidate/preview  — preview without persisting
GET  /api/v1/memories/{id}/consolidation   — provenance for a consolidated memory
GET  /api/v1/memories/{id}/consolidated-from — consolidations sourced from this memory
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.consolidation.factory import get_consolidation_provider
from app.consolidation.models import (
    ConsolidatePreviewRequest,
    ConsolidatePreviewResponse,
    ConsolidateRequest,
    ConsolidateResponse,
    ConsolidationRead,
)
from app.consolidation.service import ConsolidationService
from app.database import get_db
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider

logger = logging.getLogger("munin.consolidation")

router = APIRouter(prefix="/memories", tags=["consolidation"])


def _get_service(
    db: Session = Depends(get_db),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> ConsolidationService:
    return ConsolidationService(
        db=db,
        consolidation_provider=get_consolidation_provider(),
        embedding_provider=embedding_provider,
    )


@router.post(
    "/consolidate",
    response_model=ConsolidateResponse,
    summary="Consolidate related memories into a derived summary",
)
def consolidate_memories(
    payload: ConsolidateRequest,
    service: ConsolidationService = Depends(_get_service),
) -> ConsolidateResponse:
    """
    Consolidate a set of related active memories into one derived summary memory.

    - Source memories remain active and unchanged.
    - The derived memory is marked ``is_consolidated=True`` in metadata.
    - Full provenance is stored in ``memory_consolidations`` and
      ``memory_consolidation_sources``.
    - Idempotent: the same source set returns the existing consolidated memory.
    - ``dry_run=true``: runs the provider and returns the proposal without persisting.
    """
    return service.consolidate(
        namespace=payload.namespace,
        user_id=payload.user_id,
        memory_ids=payload.memory_ids,
        dry_run=payload.dry_run,
    )


@router.post(
    "/consolidate/preview",
    response_model=ConsolidatePreviewResponse,
    summary="Preview consolidation without persisting",
)
def preview_consolidation(
    payload: ConsolidatePreviewRequest,
    service: ConsolidationService = Depends(_get_service),
) -> ConsolidatePreviewResponse:
    """
    Run the consolidation provider and return the proposed memory.

    Nothing is persisted. Safe to call repeatedly.
    """
    return service.preview(
        namespace=payload.namespace,
        user_id=payload.user_id,
        memory_ids=payload.memory_ids,
    )


@router.get(
    "/{memory_id}/consolidation",
    response_model=ConsolidationRead,
    summary="Get consolidation provenance for a derived memory",
)
def get_consolidation_provenance(
    memory_id: str,
    service: ConsolidationService = Depends(_get_service),
) -> ConsolidationRead:
    """
    Return the consolidation record and source memories for a derived memory.

    Returns 404 if this memory was not created by consolidation.
    """
    from fastapi import HTTPException, status as http_status

    result = service.get_provenance(memory_id)
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' was not created by consolidation",
        )
    return result


@router.get(
    "/{memory_id}/consolidated-from",
    response_model=list[ConsolidationRead],
    summary="List consolidations that used this memory as a source",
)
def list_consolidations_from_source(
    memory_id: str,
    service: ConsolidationService = Depends(_get_service),
) -> list[ConsolidationRead]:
    """
    Return all consolidations that included this memory as a source.

    Empty list if this memory has not been consolidated.
    """
    return service.list_consolidations_for_source(memory_id)
