"""Deduplication application service.

Embedding similarity only shortlists candidates.
Relationship classification decides NEW / DUPLICATE / REINFORCES.
When uncertain, default to NEW (preserve information).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.deduplication.base import RelationshipError, RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.deduplication.models import DedupReasonCode, RelationshipType
from app.deduplication.normalize import normalize_for_exact_match
from app.deduplication.policy import DedupPolicyConfig, apply_relationship_policy
from app.embeddings.base import EmbeddingProvider
from app.models.deduplication import MemoryDeduplicationDecision, MemoryReinforcement
from app.models.event import Event
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.deduplication_repository import DeduplicationRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import MemoryCreate, MemorySearchRequest
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService

logger = logging.getLogger("munin.deduplication")


@dataclass
class DeduplicationResult:
    """Outcome of processing one STORE-worthy candidate."""

    relationship: RelationshipType
    confidence: float
    matched_memory_id: str | None
    created_memory_id: str | None
    created_new_memory: bool
    similarity_score: float | None
    reason_codes: list[str]
    explanation: str | None = None
    decision_id: str | None = None


class DeduplicationService:
    """Classify STORE candidates against existing memories before persistence."""

    def __init__(
        self,
        db: Session,
        *,
        relationship_provider: RelationshipProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        policy: DedupPolicyConfig | None = None,
    ) -> None:
        self.db = db
        self.repo = DeduplicationRepository(db)
        self.memory_repo = MemoryRepository(db)
        self.relationship_provider = relationship_provider or get_relationship_provider()
        self.memory_service = MemoryService(db, embedding_provider=embedding_provider)
        self.embedding_service = self.memory_service.embedding_service
        settings = get_settings()
        self.policy = policy or DedupPolicyConfig(
            min_relationship_confidence=settings.dedup_relationship_min_confidence,
            candidate_limit=settings.dedup_candidate_limit,
            min_similarity=settings.dedup_min_similarity,
        )

    def process_candidate(
        self,
        *,
        event: Event,
        admission_id: str | None,
        content: str,
        memory_type: MemoryType,
        importance: float,
        confidence: float,
        create_memory: bool = True,
    ) -> DeduplicationResult:
        """
        Decide NEW / DUPLICATE / REINFORCES and optionally create memory / reinforcement.

        Always writes a dedup audit row (within the caller's transaction).
        Does not commit — caller owns the transaction boundary.
        """
        started = time.perf_counter()
        semantic_checked = 0

        # 1) Exact / normalized duplicate (cheap path)
        exact = self._find_exact_duplicate(
            namespace=event.namespace,
            user_id=event.user_id,
            content=content,
        )
        if exact is not None:
            result = DeduplicationResult(
                relationship=RelationshipType.DUPLICATE,
                confidence=1.0,
                matched_memory_id=exact.id,
                created_memory_id=None,
                created_new_memory=False,
                similarity_score=1.0,
                reason_codes=[DedupReasonCode.EXACT_DUPLICATE.value],
                explanation="Exact or normalized duplicate of existing memory",
            )
            self._persist_decision(
                event=event,
                admission_id=admission_id,
                content=content,
                memory_type=memory_type,
                result=result,
            )
            self._log_decision(
                event_id=event.id,
                admission_id=admission_id,
                result=result,
                semantic_checked=0,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result

        # 2) Semantic shortlist (embeddings retrieve; do not decide equivalence)
        shortlist = self._retrieve_similar(
            namespace=event.namespace,
            user_id=event.user_id,
            content=content,
        )
        semantic_checked = len(shortlist)

        if not shortlist:
            result = self._finalize_new(
                event=event,
                admission_id=admission_id,
                content=content,
                memory_type=memory_type,
                importance=importance,
                confidence=confidence,
                create_memory=create_memory,
                reason_codes=[DedupReasonCode.NO_SIMILAR_CANDIDATES.value],
                explanation="No similar active memories in scope",
                similarity_score=None,
                matched_memory_id=None,
                rel_confidence=1.0,
            )
            self._log_decision(
                event_id=event.id,
                admission_id=admission_id,
                result=result,
                semantic_checked=semantic_checked,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result

        # 3) Classify against shortlist; pick best non-NEW if confident
        best_dup: tuple[Memory, float, DeduplicationResult] | None = None
        best_reinf: tuple[Memory, float, DeduplicationResult] | None = None
        uncertain_reasons: list[str] = []

        for memory, similarity in shortlist:
            outcome = self._classify_pair(
                candidate=content,
                existing=memory,
                candidate_type=memory_type,
            )
            if outcome.relationship == RelationshipType.DUPLICATE:
                cand = DeduplicationResult(
                    relationship=RelationshipType.DUPLICATE,
                    confidence=outcome.confidence,
                    matched_memory_id=memory.id,
                    created_memory_id=None,
                    created_new_memory=False,
                    similarity_score=similarity,
                    reason_codes=[c.value for c in outcome.reason_codes],
                    explanation=outcome.explanation,
                )
                if best_dup is None or cand.confidence > best_dup[2].confidence:
                    best_dup = (memory, similarity, cand)
            elif outcome.relationship == RelationshipType.REINFORCES:
                cand = DeduplicationResult(
                    relationship=RelationshipType.REINFORCES,
                    confidence=outcome.confidence,
                    matched_memory_id=memory.id,
                    created_memory_id=None,
                    created_new_memory=False,
                    similarity_score=similarity,
                    reason_codes=[c.value for c in outcome.reason_codes],
                    explanation=outcome.explanation,
                )
                if best_reinf is None or cand.confidence > best_reinf[2].confidence:
                    best_reinf = (memory, similarity, cand)
            else:
                uncertain_reasons.extend(c.value for c in outcome.reason_codes)

        if best_dup is not None:
            memory, _sim, result = best_dup
            self._persist_decision(
                event=event,
                admission_id=admission_id,
                content=content,
                memory_type=memory_type,
                result=result,
            )
            self._log_decision(
                event_id=event.id,
                admission_id=admission_id,
                result=result,
                semantic_checked=semantic_checked,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result

        if best_reinf is not None:
            memory, _sim, result = best_reinf
            self.repo.create_reinforcement(
                MemoryReinforcement(
                    memory_id=memory.id,
                    source_event_id=event.id,
                    admission_id=admission_id,
                    candidate_content=content,
                    relationship_confidence=result.confidence,
                    provider=self.relationship_provider.provider_name,
                    model_name=self.relationship_provider.model_name,
                ),
                commit=False,
            )
            # Do not overwrite original source_event_id on the canonical memory.
            self._persist_decision(
                event=event,
                admission_id=admission_id,
                content=content,
                memory_type=memory_type,
                result=result,
            )
            self._log_decision(
                event_id=event.id,
                admission_id=admission_id,
                result=result,
                semantic_checked=semantic_checked,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result

        # All classifications were NEW / uncertain
        top_sim = shortlist[0][1] if shortlist else None
        reason_codes = list(dict.fromkeys(uncertain_reasons)) or [
            DedupReasonCode.RELATED_BUT_NEW.value
        ]
        explanation = "Similar memories found but none confidently duplicate/reinforce"
        if DedupReasonCode.PROVIDER_UNAVAILABLE.value in reason_codes:
            explanation = "Relationship provider unavailable; preserving candidate as NEW"
        elif DedupReasonCode.LOW_CONFIDENCE.value in reason_codes:
            explanation = "Relationship confidence below threshold; preserving as NEW"

        result = self._finalize_new(
            event=event,
            admission_id=admission_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            confidence=confidence,
            create_memory=create_memory,
            reason_codes=reason_codes,
            explanation=explanation,
            similarity_score=top_sim,
            matched_memory_id=None,
            rel_confidence=0.8,
        )
        self._log_decision(
            event_id=event.id,
            admission_id=admission_id,
            result=result,
            semantic_checked=semantic_checked,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return result

    def list_decisions_for_event(self, event_id: str) -> list[MemoryDeduplicationDecision]:
        return self.repo.list_decisions_by_event_id(event_id)

    def _classify_pair(
        self,
        *,
        candidate: str,
        existing: Memory,
        candidate_type: MemoryType,
    ):
        try:
            analysis = self.relationship_provider.classify(
                candidate=candidate,
                existing_memory=existing.content,
                candidate_type=candidate_type,
                existing_type=existing.memory_type,
            )
            return apply_relationship_policy(analysis, config=self.policy)
        except RelationshipError:
            return apply_relationship_policy(
                None,
                config=self.policy,
                provider_error=True,
            )

    def _find_exact_duplicate(
        self,
        *,
        namespace: str,
        user_id: str | None,
        content: str,
    ) -> Memory | None:
        target = normalize_for_exact_match(content)
        # Bound scan: active memories in namespace; filter user scope in Python for NULL semantics.
        candidates = self.memory_repo.list(
            namespace=namespace,
            status=MemoryStatus.active,
            limit=500,
            offset=0,
        )
        for memory in candidates:
            if not self._user_scope_compatible(user_id, memory.user_id):
                continue
            if normalize_for_exact_match(memory.content) == target:
                return memory
        return None

    def _retrieve_similar(
        self,
        *,
        namespace: str,
        user_id: str | None,
        content: str,
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
            memory = self.memory_repo.get_by_id(hit.memory.id)
            if memory is None:
                continue
            if not self._user_scope_compatible(user_id, memory.user_id):
                continue
            results.append((memory, hit.score))
        return results

    @staticmethod
    def _user_scope_compatible(candidate_user_id: str | None, memory_user_id: str | None) -> bool:
        """Personal memories must not merge across different user_ids."""
        if candidate_user_id is None and memory_user_id is None:
            return True
        if candidate_user_id is None or memory_user_id is None:
            # One scoped, one unscoped — do not merge.
            return False
        return candidate_user_id == memory_user_id

    def _finalize_new(
        self,
        *,
        event: Event,
        admission_id: str | None,
        content: str,
        memory_type: MemoryType,
        importance: float,
        confidence: float,
        create_memory: bool,
        reason_codes: list[str],
        explanation: str | None,
        similarity_score: float | None,
        matched_memory_id: str | None,
        rel_confidence: float,
    ) -> DeduplicationResult:
        created_id: str | None = None
        if create_memory:
            memory = self.memory_service.create(
                MemoryCreate(
                    namespace=event.namespace,
                    user_id=event.user_id,
                    agent_id=event.agent_id,
                    content=content,
                    memory_type=memory_type,
                    importance=importance,
                    confidence=confidence,
                    source_event_id=event.id,
                    metadata={"admitted_from_event": True},
                ),
                commit=False,
            )
            created_id = memory.id

        result = DeduplicationResult(
            relationship=RelationshipType.NEW,
            confidence=rel_confidence,
            matched_memory_id=matched_memory_id,
            created_memory_id=created_id,
            created_new_memory=created_id is not None,
            similarity_score=similarity_score,
            reason_codes=reason_codes,
            explanation=explanation,
        )
        self._persist_decision(
            event=event,
            admission_id=admission_id,
            content=content,
            memory_type=memory_type,
            result=result,
        )
        return result

    def _persist_decision(
        self,
        *,
        event: Event,
        admission_id: str | None,
        content: str,
        memory_type: MemoryType,
        result: DeduplicationResult,
    ) -> MemoryDeduplicationDecision:
        row = MemoryDeduplicationDecision(
            event_id=event.id,
            admission_id=admission_id,
            candidate_content=content,
            candidate_memory_type=memory_type.value,
            matched_memory_id=result.matched_memory_id,
            relationship=result.relationship.value,
            relationship_confidence=result.confidence,
            similarity_score=result.similarity_score,
            reason_codes=list(result.reason_codes),
            created_memory_id=result.created_memory_id,
            provider=self.relationship_provider.provider_name,
            model_name=self.relationship_provider.model_name,
        )
        created = self.repo.create_decision(row, commit=False)
        result.decision_id = created.id
        return created

    def _log_decision(
        self,
        *,
        event_id: str,
        admission_id: str | None,
        result: DeduplicationResult,
        semantic_checked: int,
        duration_ms: int,
    ) -> None:
        logger.info(
            "Dedup event_id=%s admission_id=%s relationship=%s matched_memory_id=%s "
            "created_memory_id=%s similarity=%s confidence=%s semantic_checked=%s "
            "provider=%s model=%s duration_ms=%s",
            event_id,
            admission_id,
            result.relationship.value,
            result.matched_memory_id,
            result.created_memory_id,
            result.similarity_score,
            result.confidence,
            semantic_checked,
            self.relationship_provider.provider_name,
            self.relationship_provider.model_name,
            duration_ms,
        )
