"""POST /api/v1/context — context assembly endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.context.service import ContextService
from app.database import get_db
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.schemas.context import ContextRequest, ContextResponse

logger = logging.getLogger("munin.context")

router = APIRouter(prefix="/context", tags=["context"])


@router.post("", response_model=ContextResponse, summary="Assemble agent context")
def assemble_context(
    payload: ContextRequest,
    db: Session = Depends(get_db),
    provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> ContextResponse:
    """
    Assemble durable memories relevant to an agent's current task.

    This is a **read-only** operation — no memory state is mutated.

    The pipeline:
    1. Embeds the query once using the active embedding provider.
    2. Retrieves candidates filtered by namespace / user / agent / type / status.
    3. Applies temporal validity filtering (valid_from / valid_until at `as_of`).
    4. Scores candidates (semantic + importance + confidence + recency + type + reinforcement).
    5. Suppresses near-duplicate memories.
    6. Selects within the requested token budget.
    7. Returns formatted context + explainability trace.
    """
    service = ContextService(db=db, provider=provider)
    return service.assemble(payload)
