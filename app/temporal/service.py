"""Temporal relationship application service.

Applies only after M3 classifies a candidate as NEW.
Embedding similarity only shortlists candidates.
When uncertain, default to NEW (do not supersede).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.embeddings.base import EmbeddingProvider
from app.models.event import Event
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.models.temporal import MemoryTemporalDecision
from app.repositories.memory_repository import MemoryRepository
from app.repositories.temporal_repository import TemporalRepository
from app.schemas.memory import MemorySearchRequest
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService
from app.temporal.base import TemporalRelationshipError, TemporalRelationshipProvider
from app.temporal.factory import get_temporal_provider
from app.temporal.models import TemporalReasonCode, TemporalRelationshipType
from app.temporal.policy import TemporalPolicyConfig, apply_temporal_policy

logger = logging.getLogger("munin.temporal")


@dataclass
class TemporalResult:
    """Outcome of temporal processing for an M3-NEW candidate."""

    relationship: TemporalRelationshipType
    confidence: float
    matched_memory_id: str | None
    created_memory_id: str | None
    old_memory_status: str | None
    similarity_score: float | None
    reason_codes: list[str]
    explanation: str | None = None
    decision_id: str | None = None


class TemporalService:
    """Classify NEW candidates against related active memories and apply transitions."""

    def __init__(
        self,
        db: Session,
        *,
        temporal_provider: TemporalRelationshipProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        policy: TemporalPolicyConfig | None = None,
    ) -> None:
        self.db = db
        self.repo = TemporalRepository(db)
        self.memory_repo = MemoryRepository(db)
        self.temporal_provider = temporal_provider or get_temporal_provider()
        self.memory_service = MemoryService(db, embedding_provider=embedding_provider)
        self.embedding_service = self.memory_service.embedding_service
        settings = get_settings()
        self.policy = policy or TemporalPolicyConfig(
            min_relationship_confidence=settings.temporal_relationship_min_confidence,
            candidate_limit=settings.temporal_candidate_limit,
            min_similarity=settings.temporal_min_similarity,
        )

    def process_new_candidate(
        self,
        *,
        event: Event,
        admission_id: str | None,
        dedup_decision_id: str | None,
        content: str,
        memory_type: MemoryType,
        created_memory_id: str,
    ) -> TemporalResult:
        """
        Run temporal classification for a memory just created by M3 NEW.

        Does not commit — caller owns the transaction boundary.
        effective_time = event.created_at
        """
        started = time.perf_counter()
        effective_time = event.created_at

        shortlist = self._retrieve_similar(
            namespace=event.namespace,
            user_id=event.user_id,
            content=content,
            exclude_memory_id=created_memory_id,
        )

        if not shortlist:
            result = TemporalResult(
                relationship=TemporalRelationshipType.NEW,
                confidence=1.0,
                matched_memory_id=None,
                created_memory_id=created_memory_id,
                old_memory_status=None,
                similarity_score=None,
                reason_codes=[TemporalReasonCode.NO_SIMILAR_CANDIDATES.value],
                explanation="No related active memories in scope",
            )
            decision = self._persist_decision(
                event=event,
                admission_id=admission_id,
                dedup_decision_id=dedup_decision_id,
                content=content,
                memory_type=memory_type,
                result=result,
            )
            result.decision_id = decision.id
            self._log(event.id, admission_id, result, 0, started)
            return result

        best: tuple[Memory, float, TemporalResult] | None = None
        uncertain_reasons: list[str] = []

        for memory, similarity in shortlist:
            outcome = self._classify_pair(
                candidate=content,
                existing=memory,
                candidate_type=memory_type,
                event_time=effective_time,
            )
            if outcome.relationship == TemporalRelationshipType.NEW:
                uncertain_reasons.extend(c.value for c in outcome.reason_codes)
                continue

            cand = TemporalResult(
                relationship=outcome.relationship,
                confidence=outcome.confidence,
                matched_memory_id=memory.id,
                created_memory_id=created_memory_id,
                old_memory_status=memory.status.value
                if hasattr(memory.status, "value")
                else str(memory.status),
                similarity_score=similarity,
                reason_codes=[c.value for c in outcome.reason_codes],
                explanation=outcome.explanation,
            )
            if best is None or cand.confidence > best[2].confidence:
                best = (memory, similarity, cand)

        if best is None:
            reason_codes = list(dict.fromkeys(uncertain_reasons)) or [
                TemporalReasonCode.RELATED_BUT_NEW.value
            ]
            result = TemporalResult(
                relationship=TemporalRelationshipType.NEW,
                confidence=0.8,
                matched_memory_id=None,
                created_memory_id=created_memory_id,
                old_memory_status=None,
                similarity_score=shortlist[0][1],
                reason_codes=reason_codes,
                explanation="Related memories found but no confident temporal transition",
            )
            decision = self._persist_decision(
                event=event,
                admission_id=admission_id,
                dedup_decision_id=dedup_decision_id,
                content=content,
                memory_type=memory_type,
                result=result,
            )
            result.decision_id = decision.id
            self._log(event.id, admission_id, result, len(shortlist), started)
            return result

        memory, _sim, result = best
        old_status_before = (
            memory.status.value if hasattr(memory.status, "value") else str(memory.status)
        )
        old_valid_until_before = memory.valid_until

        if result.relationship in {
            TemporalRelationshipType.SUPERSEDES,
            TemporalRelationshipType.UPDATES,
        }:
            # Atomic state transition within caller's transaction.
            memory.status = MemoryStatus.superseded
            memory.valid_until = effective_time
            self.db.add(memory)

            new_memory = self.memory_repo.get_by_id(created_memory_id)
            if new_memory is None:
                raise RuntimeError(
                    f"created memory '{created_memory_id}' missing during temporal transition"
                )
            new_memory.valid_from = effective_time
            self.db.add(new_memory)
            self.db.flush()

            result.old_memory_status = MemoryStatus.superseded.value
            decision = self._persist_decision(
                event=event,
                admission_id=admission_id,
                dedup_decision_id=dedup_decision_id,
                content=content,
                memory_type=memory_type,
                result=result,
                old_status=old_status_before,
                new_old_status=MemoryStatus.superseded.value,
                old_valid_until_before=old_valid_until_before,
                old_valid_until_after=effective_time,
                new_valid_from=effective_time,
            )
        else:
            # CONTRADICTS: keep both active; record conflict via temporal audit.
            result.old_memory_status = old_status_before
            decision = self._persist_decision(
                event=event,
                admission_id=admission_id,
                dedup_decision_id=dedup_decision_id,
                content=content,
                memory_type=memory_type,
                result=result,
                old_status=old_status_before,
                new_old_status=old_status_before,
            )

        result.decision_id = decision.id
        self._log(event.id, admission_id, result, len(shortlist), started)
        return result

    def list_for_event(self, event_id: str) -> list[MemoryTemporalDecision]:
        return self.repo.list_by_event_id(event_id)

    def history_for_memory(self, memory_id: str) -> list[MemoryTemporalDecision]:
        return self.repo.list_for_memory(memory_id)

    def _classify_pair(
        self,
        *,
        candidate: str,
        existing: Memory,
        candidate_type: MemoryType,
        event_time: datetime | None,
    ):
        try:
            analysis = self.temporal_provider.classify(
                candidate=candidate,
                existing_memory=existing.content,
                candidate_type=candidate_type,
                existing_type=existing.memory_type,
                candidate_event_time=event_time,
                existing_valid_from=existing.valid_from,
                existing_valid_until=existing.valid_until,
            )
            return apply_temporal_policy(analysis, config=self.policy)
        except TemporalRelationshipError:
            return apply_temporal_policy(
                None,
                config=self.policy,
                provider_error=True,
            )

    def _retrieve_similar(
        self,
        *,
        namespace: str,
        user_id: str | None,
        content: str,
        exclude_memory_id: str,
    ) -> list[tuple[Memory, float]]:
        search = self.embedding_service.search(
            MemorySearchRequest(
                query=content,
                namespace=namespace,
                user_id=user_id,
                statuses=[MemoryStatus.active],
                limit=self.policy.candidate_limit,
                min_score=self.policy.min_similarity,
            )
        )
        results: list[tuple[Memory, float]] = []
        for hit in search.results:
            if hit.memory.id == exclude_memory_id:
                continue
            memory = self.memory_repo.get_by_id(hit.memory.id)
            if memory is None:
                continue
            if not self._user_scope_compatible(user_id, memory.user_id):
                continue
            if memory.status != MemoryStatus.active:
                continue
            results.append((memory, hit.score))
        return results

    @staticmethod
    def _user_scope_compatible(
        candidate_user_id: str | None, memory_user_id: str | None
    ) -> bool:
        if candidate_user_id is None and memory_user_id is None:
            return True
        if candidate_user_id is None or memory_user_id is None:
            return False
        return candidate_user_id == memory_user_id

    def _persist_decision(
        self,
        *,
        event: Event,
        admission_id: str | None,
        dedup_decision_id: str | None,
        content: str,
        memory_type: MemoryType,
        result: TemporalResult,
        old_status: str | None = None,
        new_old_status: str | None = None,
        old_valid_until_before: datetime | None = None,
        old_valid_until_after: datetime | None = None,
        new_valid_from: datetime | None = None,
    ) -> MemoryTemporalDecision:
        row = MemoryTemporalDecision(
            event_id=event.id,
            admission_id=admission_id,
            dedup_decision_id=dedup_decision_id,
            candidate_content=content,
            candidate_memory_type=memory_type.value,
            matched_memory_id=result.matched_memory_id,
            created_memory_id=result.created_memory_id,
            relationship=result.relationship.value,
            relationship_confidence=result.confidence,
            similarity_score=result.similarity_score,
            reason_codes=list(result.reason_codes),
            old_status=old_status or result.old_memory_status,
            new_old_status=new_old_status,
            old_valid_until_before=old_valid_until_before,
            old_valid_until_after=old_valid_until_after,
            new_valid_from=new_valid_from,
            provider=self.temporal_provider.provider_name,
            model_name=self.temporal_provider.model_name,
        )
        return self.repo.create(row, commit=False)

    def _log(
        self,
        event_id: str,
        admission_id: str | None,
        result: TemporalResult,
        semantic_checked: int,
        started: float,
    ) -> None:
        logger.info(
            "Temporal event_id=%s admission_id=%s relationship=%s matched_memory_id=%s "
            "created_memory_id=%s old_status=%s similarity=%s confidence=%s "
            "semantic_checked=%s provider=%s model=%s duration_ms=%s",
            event_id,
            admission_id,
            result.relationship.value,
            result.matched_memory_id,
            result.created_memory_id,
            result.old_memory_status,
            result.similarity_score,
            result.confidence,
            semantic_checked,
            self.temporal_provider.provider_name,
            self.temporal_provider.model_name,
            int((time.perf_counter() - started) * 1000),
        )
