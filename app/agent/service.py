"""High-level agent service (M7A).

The AgentService is a thin orchestration layer over the existing engine. It
performs the complete event -> admission (M2) -> dedup (M3) -> temporal (M4)
pipeline for a ``remember`` call, and it **delegates** context assembly to the
existing ``ContextService`` (never re-implements ranking).

External agents interact only with these high-level methods.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.admission.base import AdmissionProvider
from app.admission.factory import get_admission_provider
from app.admission.service import AdmissionService
from app.agent.models import (
    AgentContextRequest,
    AgentContextResponse,
    AgentRememberRequest,
    AgentRememberResponse,
)
from app.config import get_settings
from app.context.service import ContextService
from app.deduplication.base import RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.repositories.event_repository import EventRepository
from app.schemas.context import ContextRequest
from app.schemas.event import EventCreate
from app.services.event_service import EventService

logger = logging.getLogger("munin.agent")


class AgentService:
    """Orchestrate the high-level agent contract against the engine."""

    def __init__(
        self,
        db: Session,
        *,
        admission_provider: AdmissionProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        relationship_provider: RelationshipProvider | None = None,
    ) -> None:
        self.db = db
        self.admission_provider = admission_provider or get_admission_provider()
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.relationship_provider = relationship_provider or get_relationship_provider()
        self.event_repo = EventRepository(db)
        self.event_service = EventService(db)
        self.context_service = ContextService(db, provider=self.embedding_provider)
# ------------------------------------------------------------------
    # remember
    # ------------------------------------------------------------------

    def remember(self, payload: AgentRememberRequest) -> AgentRememberResponse:
        """Create an event and run the full admission pipeline.

        Idempotency: if ``idempotency_key`` matches an existing event in the
        same scope, replay that event's admission (existing clean path) and
        return the original outcome without creating a new event/memory.
        """
        if payload.idempotency_key:
            existing = self.event_repo.find_by_idempotency_key(
                namespace=payload.namespace,
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                key=payload.idempotency_key,
            )
            if existing is not None:
                admit = self._admit(existing.id)
                return self._compact(
                    event_id=existing.id, admit=admit, idempotent_replay=True
                )

        metadata = {"explicit_remember": True}
        if payload.idempotency_key:
            metadata["idempotency_key"] = payload.idempotency_key

        event = self.event_service.create(
            EventCreate(
                namespace=payload.namespace,
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                session_id=payload.session_id,
                role=payload.role,
                content=payload.content,
                metadata=metadata,
            )
        )
        admit = self._admit(event.id)
        return self._compact(event_id=event.id, admit=admit, idempotent_replay=False)

    # ------------------------------------------------------------------
    # context (delegates to existing ContextService — no duplicate ranking)
    # ------------------------------------------------------------------

    def get_context(self, payload: AgentContextRequest) -> AgentContextResponse:
        """Assemble durable memory context via the existing ContextService."""
        ctx = ContextRequest(
            query=payload.query,
            namespace=payload.namespace,
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            token_budget=payload.token_budget,
            max_memories=payload.max_memories,
            max_candidates=min(payload.max_memories * 5, get_settings().context_max_candidates),
        )
        assembled = self.context_service.assemble(ctx)
        return AgentContextResponse(
            query=assembled.query,
            namespace=assembled.namespace,
            text=assembled.context,
            estimated_tokens=assembled.estimated_tokens,
            truncated=assembled.truncated,
            memories_used=assembled.memories_used,
            as_of=ctx.as_of,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _admit(self, event_id: str):
        """Run the full admission pipeline for an event (idempotent-safe)."""
        service = AdmissionService(
            self.db,
            admission_provider=self.admission_provider,
            embedding_provider=self.embedding_provider,
            relationship_provider=self.relationship_provider,
        )
        return service.admit_event(event_id)

    def _compact(
        self, *, event_id: str, admit, idempotent_replay: bool
    ) -> AgentRememberResponse:
        stored = [r for r in admit.results if r.decision == "STORE"]
        if stored:
            first = stored[0]
            return AgentRememberResponse(
                event_id=event_id,
                remembered=True,
                decision="STORE",
                memory_id=first.memory_id,
                dedup_relationship=(
                    first.deduplication.relationship if first.deduplication else None
                ),
                temporal_relationship=(
                    first.temporal.relationship if first.temporal else None
                ),
                idempotent_replay=idempotent_replay,
            )
        return AgentRememberResponse(
            event_id=event_id,
            remembered=False,
            decision="IGNORE",
            memory_id=None,
            dedup_relationship=None,
            temporal_relationship=None,
            idempotent_replay=idempotent_replay,
        )