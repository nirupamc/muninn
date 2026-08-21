"""Context assembly application service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.context.assembler import ContextAssembler
from app.context.models import ContextConfig
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.schemas.context import ContextRequest, ContextResponse, MemoryUsed

logger = logging.getLogger("munin.context")


def _config_from_request(req: ContextRequest) -> ContextConfig:
    """Build a ContextConfig merging request overrides with global settings."""
    settings = get_settings()
    return ContextConfig(
        max_candidates=req.max_candidates,
        max_memories=req.max_memories,
        token_budget=req.token_budget,
        max_token_budget=settings.context_max_token_budget,
        redundancy_threshold=settings.context_redundancy_threshold,
        weight_semantic=settings.context_weight_semantic,
        weight_importance=settings.context_weight_importance,
        weight_confidence=settings.context_weight_confidence,
        weight_recency=settings.context_weight_recency,
        weight_type_relevance=settings.context_weight_type_relevance,
        weight_reinforcement=settings.context_weight_reinforcement,
        recency_lambda=settings.context_recency_lambda,
    )


class ContextService:
    """
    Orchestrate context assembly without mutating any memory state.

    M5 is intentionally read-only: no importance/confidence/status changes,
    no last_accessed_at update, no reinforcement writes.
    """

    def __init__(
        self,
        db: Session,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.provider = provider or get_embedding_provider()

    def assemble(self, req: ContextRequest) -> ContextResponse:
        """
        Assemble context for the given request.

        Raises nothing on empty results — returns a valid empty response.
        """
        as_of = req.as_of
        if as_of is None:
            as_of = datetime.now(UTC)
        elif as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)

        config = _config_from_request(req)

        assembler = ContextAssembler(
            db=self.db,
            config=config,
            provider=self.provider,
        )

        selected, context_text, final_tokens, truncated, _trace = assembler.assemble(
            query=req.query,
            namespace=req.namespace,
            user_id=req.user_id,
            agent_id=req.agent_id,
            as_of=as_of,
            include_superseded=req.include_superseded,
            memory_types=req.memory_types,
            max_candidates=req.max_candidates,
            max_memories=req.max_memories,
            token_budget=req.token_budget,
        )

        memories_used = [
            MemoryUsed(
                memory_id=m.memory_id,
                memory_type=m.memory_type,
                content=m.content,
                semantic_score=m.semantic_score,
                importance=m.importance,
                confidence=m.confidence,
                recency_score=m.recency_score,
                type_relevance=m.type_relevance,
                reinforcement_score=m.reinforcement_score,
                final_score=m.final_score,
                estimated_tokens=m.estimated_tokens,
                reason_codes=m.reason_codes,
            )
            for m in selected
        ]

        return ContextResponse(
            query=req.query,
            namespace=req.namespace,
            context=context_text,
            token_budget=req.token_budget,
            estimated_tokens=final_tokens,
            truncated=truncated,
            memories_used=memories_used,
        )
