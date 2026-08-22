"""Agent-facing HTTP endpoints (M7A).

POST /api/v1/agent/remember — high-level remember flow
POST /api/v1/agent/context  — high-level context retrieval

These wrappers hide internal pipeline complexity. Context delegates to the
existing ContextService; no ranking logic is duplicated here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.admission.base import AdmissionProvider
from app.admission.factory import get_admission_provider
from app.agent.models import (
    AgentContextRequest,
    AgentContextResponse,
    AgentRememberRequest,
    AgentRememberResponse,
)
from app.agent.service import AgentService
from app.database import get_db
from app.deduplication.base import RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider

logger = logging.getLogger("munin.agent")

router = APIRouter(prefix="/agent", tags=["agent"])


def _get_agent_service(
    db: Session = Depends(get_db),
    admission_provider: AdmissionProvider = Depends(get_admission_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    relationship_provider: RelationshipProvider = Depends(get_relationship_provider),
) -> AgentService:
    return AgentService(
        db,
        admission_provider=admission_provider,
        embedding_provider=embedding_provider,
        relationship_provider=relationship_provider,
    )


@router.post(
    "/remember",
    response_model=AgentRememberResponse,
    summary="Remember a useful interaction (high-level)",
)
def agent_remember(
    payload: AgentRememberRequest,
    service: AgentService = Depends(_get_agent_service),
) -> AgentRememberResponse:
    """Persist an interaction through the full admission pipeline.

    Creates an event, runs admission (M2), deduplication (M3), and temporal
    reasoning (M4), then returns a compact high-level outcome.
    """
    return service.remember(payload)


@router.post(
    "/context",
    response_model=AgentContextResponse,
    summary="Retrieve agent-ready durable memory context",
)
def agent_context(
    payload: AgentContextRequest,
    service: AgentService = Depends(_get_agent_service),
) -> AgentContextResponse:
    """Assemble durable memory context for an external agent.

    Delegates to the existing ContextService. The response ``text`` is data,
    not a privileged system instruction.
    """
    return service.get_context(payload)