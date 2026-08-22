"""Memory admission application service."""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.admission.base import AdmissionError, AdmissionProvider
from app.admission.factory import get_admission_provider
from app.admission.models import ReasonCode
from app.admission.privacy import REDACTED_PLACEHOLDER, contains_secret_like_data, redact_if_sensitive
from app.admission.rules import AdmissionPolicyConfig, PolicyDecision, apply_admission_policy
from app.config import get_settings
from app.deduplication.base import RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.deduplication.models import RelationshipType
from app.deduplication.service import DeduplicationService
from app.embeddings.base import EmbeddingProvider
from app.models.admission import MemoryAdmission
from app.models.deduplication import MemoryDeduplicationDecision
from app.models.memory import MemoryType
from app.models.temporal import MemoryTemporalDecision
from app.repositories.admission_repository import AdmissionRepository
from app.repositories.event_repository import EventRepository
from app.schemas.admission import (
    AdmitEventResponse,
    AdmitEventResultItem,
    AnalyzeAdmissionCandidate,
    AnalyzeAdmissionRequest,
    AnalyzeAdmissionResponse,
    DeduplicationOutcomeRead,
    TemporalOutcomeRead,
)
from app.temporal.service import TemporalService

logger = logging.getLogger("munin.admission")


class AdmissionService:
    """Orchestrates event → candidates → policy → audit → dedup → memory."""

    def __init__(
        self,
        db: Session,
        *,
        admission_provider: AdmissionProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        relationship_provider: RelationshipProvider | None = None,
    ) -> None:
        self.db = db
        self.event_repo = EventRepository(db)
        self.admission_repo = AdmissionRepository(db)
        self.admission_provider = admission_provider or get_admission_provider()
        self.dedup_service = DeduplicationService(
            db,
            relationship_provider=relationship_provider,
            embedding_provider=embedding_provider,
        )
        self.temporal_service = TemporalService(
            db,
            embedding_provider=embedding_provider,
        )
        settings = get_settings()
        self.policy = AdmissionPolicyConfig(
            store_threshold=settings.admission_store_threshold,
            min_confidence=settings.admission_min_confidence,
        )

    def admit_event(self, event_id: str) -> AdmitEventResponse:
        event = self.event_repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event '{event_id}' not found",
            )

        existing = self.admission_repo.list_by_event_id(event_id)
        if existing:
            dedup_rows = self.dedup_service.list_decisions_for_event(event_id)
            temporal_rows = self.temporal_service.list_for_event(event_id)
            return self._response_from_audits(
                event_id,
                existing,
                dedup_rows,
                temporal_rows,
                idempotent_replay=True,
            )

        started = time.perf_counter()
        try:
            explicit_remember = bool(
                event.metadata_ and event.metadata_.get("explicit_remember") is True
            )
            analysis = self.admission_provider.analyze_event(
                role=event.role.value if hasattr(event.role, "value") else str(event.role),
                content=event.content,
                context={
                    "namespace": event.namespace,
                    "user_id": event.user_id,
                    "agent_id": event.agent_id,
                    "session_id": event.session_id,
                },
                explicit_remember=explicit_remember,
            )
        except AdmissionError as exc:
            logger.error(
                "Admission provider unavailable event_id=%s provider=%s",
                event_id,
                self.admission_provider.provider_name,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admission provider unavailable",
            ) from exc

        if contains_secret_like_data(event.content).is_sensitive and not analysis.candidates:
            analysis_candidates = []
        else:
            analysis_candidates = analysis.candidates

        if contains_secret_like_data(event.content).is_sensitive and not analysis_candidates:
            from app.admission.models import (
                AdmissionCandidate,
                CandidateAnalysis,
            )

            analysis_candidates = [
                CandidateAnalysis(
                    candidate=AdmissionCandidate(
                        content="Sensitive content withheld.",
                        memory_type=MemoryType.other,
                        importance=0.0,
                        confidence=1.0,
                        future_utility=0.0,
                        stability=0.0,
                        specificity=0.0,
                        explicitness=1.0,
                        triviality=1.0,
                    ),
                    provider_recommendation="IGNORE",
                    reason_codes=[ReasonCode.SECRET_LIKE_DATA],
                    explanation="Secret-like event content",
                )
            ]

        decisions: list[PolicyDecision] = [
            apply_admission_policy(
                item,
                source_event_content=event.content,
                config=self.policy,
            )
            for item in analysis_candidates
        ]

        try:
            audits: list[MemoryAdmission] = []
            results: list[AdmitEventResultItem] = []
            dedup_by_admission: dict[str, DeduplicationOutcomeRead] = {}

            for decision in decisions:
                memory_id: str | None = None
                dedup_outcome: DeduplicationOutcomeRead | None = None
                temporal_outcome: TemporalOutcomeRead | None = None

                safe_content = (
                    REDACTED_PLACEHOLDER
                    if decision.redacted
                    else decision.candidate.content
                )

                # Persist admission audit first (STORE remains STORE even if later deduped).
                audit = MemoryAdmission(
                    event_id=event.id,
                    candidate_content=safe_content,
                    memory_type=decision.candidate.memory_type.value,
                    decision=decision.decision,
                    admission_score=decision.admission_score,
                    importance=decision.candidate.importance,
                    confidence=decision.candidate.confidence,
                    future_utility=decision.candidate.future_utility,
                    stability=decision.candidate.stability,
                    specificity=decision.candidate.specificity,
                    explicitness=decision.candidate.explicitness,
                    triviality=decision.candidate.triviality,
                    reason_codes=[c.value for c in decision.reason_codes],
                    created_memory_id=None,
                    provider=self.admission_provider.provider_name,
                    model_name=self.admission_provider.model_name,
                )
                self.admission_repo.create(audit, commit=False)

                if decision.decision == "STORE" and not decision.redacted:
                    dedup_result = self.dedup_service.process_candidate(
                        event=event,
                        admission_id=audit.id,
                        content=decision.candidate.content,
                        memory_type=decision.candidate.memory_type,
                        importance=decision.candidate.importance,
                        confidence=decision.candidate.confidence,
                        create_memory=True,
                    )
                    memory_id = dedup_result.created_memory_id
                    audit.created_memory_id = memory_id
                    self.db.add(audit)
                    self.db.flush()

                    dedup_outcome = DeduplicationOutcomeRead(
                        relationship=dedup_result.relationship.value,
                        matched_memory_id=dedup_result.matched_memory_id,
                        created_new_memory=dedup_result.created_new_memory,
                        relationship_confidence=dedup_result.confidence,
                        similarity_score=dedup_result.similarity_score,
                        reason_codes=list(dedup_result.reason_codes),
                    )
                    dedup_by_admission[audit.id] = dedup_outcome

                    if (
                        dedup_result.relationship == RelationshipType.NEW
                        and dedup_result.created_memory_id
                    ):
                        temporal_result = self.temporal_service.process_new_candidate(
                            event=event,
                            admission_id=audit.id,
                            dedup_decision_id=dedup_result.decision_id,
                            content=decision.candidate.content,
                            memory_type=decision.candidate.memory_type,
                            created_memory_id=dedup_result.created_memory_id,
                        )
                        temporal_outcome = TemporalOutcomeRead(
                            relationship=temporal_result.relationship.value,
                            matched_memory_id=temporal_result.matched_memory_id,
                            created_memory_id=temporal_result.created_memory_id,
                            old_memory_status=temporal_result.old_memory_status,
                            relationship_confidence=temporal_result.confidence,
                            similarity_score=temporal_result.similarity_score,
                            reason_codes=list(temporal_result.reason_codes),
                        )

                audits.append(audit)
                results.append(
                    AdmitEventResultItem(
                        decision=decision.decision,
                        memory_id=memory_id,
                        memory_type=decision.candidate.memory_type,
                        content=safe_content,
                        admission_score=round(decision.admission_score, 6),
                        importance=decision.candidate.importance,
                        confidence=decision.candidate.confidence,
                        future_utility=decision.candidate.future_utility,
                        stability=decision.candidate.stability,
                        specificity=decision.candidate.specificity,
                        explicitness=decision.candidate.explicitness,
                        triviality=decision.candidate.triviality,
                        reason_codes=[c.value for c in decision.reason_codes],
                        deduplication=dedup_outcome,
                        temporal=temporal_outcome,
                    )
                )

            if not decisions:
                audit = MemoryAdmission(
                    event_id=event.id,
                    candidate_content=None,
                    memory_type=None,
                    decision="IGNORE",
                    admission_score=0.0,
                    importance=None,
                    confidence=None,
                    future_utility=None,
                    stability=None,
                    specificity=None,
                    explicitness=None,
                    triviality=None,
                    reason_codes=[ReasonCode.LOW_FUTURE_UTILITY.value],
                    created_memory_id=None,
                    provider=self.admission_provider.provider_name,
                    model_name=self.admission_provider.model_name,
                )
                self.admission_repo.create(audit, commit=False)
                audits.append(audit)
                results.append(
                    AdmitEventResultItem(
                        decision="IGNORE",
                        memory_id=None,
                        memory_type=None,
                        content=None,
                        admission_score=0.0,
                        reason_codes=[ReasonCode.LOW_FUTURE_UTILITY.value],
                    )
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        # "stored" = admission STORE decisions (M2 meaning). Dedup may not create a row.
        stored = sum(1 for r in results if r.decision == "STORE")
        ignored = sum(1 for r in results if r.decision == "IGNORE")
        created = sum(
            1
            for r in results
            if r.deduplication is not None and r.deduplication.created_new_memory
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Admitted event_id=%s candidates=%s store_worthy=%s created_memories=%s "
            "ignored=%s provider=%s model=%s duration_ms=%s",
            event_id,
            len(results),
            stored,
            created,
            ignored,
            self.admission_provider.provider_name,
            self.admission_provider.model_name,
            elapsed_ms,
        )
        return AdmitEventResponse(
            event_id=event_id,
            processed=len(results),
            stored=stored,
            ignored=ignored,
            results=results,
            idempotent_replay=False,
        )

    def list_admissions(self, event_id: str) -> list[MemoryAdmission]:
        event = self.event_repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event '{event_id}' not found",
            )
        return self.admission_repo.list_by_event_id(event_id)

    def list_deduplication(self, event_id: str) -> list[MemoryDeduplicationDecision]:
        event = self.event_repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event '{event_id}' not found",
            )
        return self.dedup_service.list_decisions_for_event(event_id)

    def list_temporal(self, event_id: str) -> list[MemoryTemporalDecision]:
        event = self.event_repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event '{event_id}' not found",
            )
        return self.temporal_service.list_for_event(event_id)

    def analyze_only(self, payload: AnalyzeAdmissionRequest) -> AnalyzeAdmissionResponse:
        """Debug analysis — no persistence, no memory creation."""
        try:
            analysis = self.admission_provider.analyze_event(
                role=payload.role.value,
                content=payload.content,
            )
        except AdmissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admission provider unavailable",
            ) from exc

        results: list[AnalyzeAdmissionCandidate] = []
        for item in analysis.candidates:
            decision = apply_admission_policy(
                item,
                source_event_content=payload.content,
                config=self.policy,
            )
            safe_content = (
                REDACTED_PLACEHOLDER if decision.redacted else decision.candidate.content
            )
            results.append(
                AnalyzeAdmissionCandidate(
                    decision=decision.decision,
                    content=safe_content,
                    memory_type=decision.candidate.memory_type,
                    admission_score=round(decision.admission_score, 6),
                    importance=decision.candidate.importance,
                    confidence=decision.candidate.confidence,
                    future_utility=decision.candidate.future_utility,
                    stability=decision.candidate.stability,
                    specificity=decision.candidate.specificity,
                    explicitness=decision.candidate.explicitness,
                    triviality=decision.candidate.triviality,
                    reason_codes=[c.value for c in decision.reason_codes],
                    explanation=decision.explanation,
                )
            )

        return AnalyzeAdmissionResponse(
            processed=len(results),
            would_store=sum(1 for r in results if r.decision == "STORE"),
            would_ignore=sum(1 for r in results if r.decision == "IGNORE"),
            results=results,
            provider=self.admission_provider.provider_name,
            model_name=self.admission_provider.model_name,
        )

    def _response_from_audits(
        self,
        event_id: str,
        audits: list[MemoryAdmission],
        dedup_rows: list[MemoryDeduplicationDecision],
        temporal_rows: list[MemoryTemporalDecision],
        *,
        idempotent_replay: bool,
    ) -> AdmitEventResponse:
        dedup_by_admission = {row.admission_id: row for row in dedup_rows if row.admission_id}
        temporal_by_admission = {
            row.admission_id: row for row in temporal_rows if row.admission_id
        }
        # Fallback: match by order for legacy rows without admission_id linkage.
        unmatched_dedup = [row for row in dedup_rows if not row.admission_id]
        unmatched_temporal = [row for row in temporal_rows if not row.admission_id]
        unmatched_idx = 0
        unmatched_temporal_idx = 0

        results: list[AdmitEventResultItem] = []
        for row in audits:
            dedup_outcome: DeduplicationOutcomeRead | None = None
            temporal_outcome: TemporalOutcomeRead | None = None
            dedup_row = dedup_by_admission.get(row.id)
            temporal_row = temporal_by_admission.get(row.id)
            if dedup_row is None and row.decision == "STORE" and unmatched_idx < len(unmatched_dedup):
                dedup_row = unmatched_dedup[unmatched_idx]
                unmatched_idx += 1
            if dedup_row is not None:
                dedup_outcome = DeduplicationOutcomeRead(
                    relationship=dedup_row.relationship,
                    matched_memory_id=dedup_row.matched_memory_id,
                    created_new_memory=dedup_row.created_memory_id is not None,
                    relationship_confidence=dedup_row.relationship_confidence,
                    similarity_score=dedup_row.similarity_score,
                    reason_codes=list(dedup_row.reason_codes or []),
                )

            if temporal_row is None and row.decision == "STORE" and unmatched_temporal_idx < len(
                unmatched_temporal
            ):
                temporal_row = unmatched_temporal[unmatched_temporal_idx]
                unmatched_temporal_idx += 1
            if temporal_row is not None:
                temporal_outcome = TemporalOutcomeRead(
                    relationship=temporal_row.relationship,
                    matched_memory_id=temporal_row.matched_memory_id,
                    created_memory_id=temporal_row.created_memory_id,
                    old_memory_status=temporal_row.new_old_status or temporal_row.old_status,
                    relationship_confidence=temporal_row.relationship_confidence,
                    similarity_score=temporal_row.similarity_score,
                    reason_codes=list(temporal_row.reason_codes or []),
                )

            results.append(
                AdmitEventResultItem(
                    decision=row.decision,
                    memory_id=row.created_memory_id,
                    memory_type=row.memory_type,
                    content=redact_if_sensitive(row.candidate_content)
                    if row.candidate_content
                    else row.candidate_content,
                    admission_score=row.admission_score,
                    importance=row.importance,
                    confidence=row.confidence,
                    future_utility=row.future_utility,
                    stability=row.stability,
                    specificity=row.specificity,
                    explicitness=row.explicitness,
                    triviality=row.triviality,
                    reason_codes=list(row.reason_codes or []),
                    deduplication=dedup_outcome,
                    temporal=temporal_outcome,
                )
            )

        return AdmitEventResponse(
            event_id=event_id,
            processed=len(results),
            stored=sum(1 for r in results if r.decision == "STORE"),
            ignored=sum(1 for r in results if r.decision == "IGNORE"),
            results=results,
            idempotent_replay=idempotent_replay,
        )
