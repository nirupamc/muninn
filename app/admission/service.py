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
from app.embeddings.base import EmbeddingProvider
from app.models.admission import MemoryAdmission
from app.models.event import Event
from app.repositories.admission_repository import AdmissionRepository
from app.repositories.event_repository import EventRepository
from app.schemas.admission import (
    AdmitEventResponse,
    AdmitEventResultItem,
    AnalyzeAdmissionCandidate,
    AnalyzeAdmissionRequest,
    AnalyzeAdmissionResponse,
)
from app.schemas.memory import MemoryCreate
from app.services.memory_service import MemoryService

logger = logging.getLogger("munin.admission")


class AdmissionService:
    """Orchestrates event → candidates → policy → audit → memory."""

    def __init__(
        self,
        db: Session,
        *,
        admission_provider: AdmissionProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.event_repo = EventRepository(db)
        self.admission_repo = AdmissionRepository(db)
        self.admission_provider = admission_provider or get_admission_provider()
        self.memory_service = MemoryService(db, embedding_provider=embedding_provider)
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
            return self._response_from_audits(event_id, existing, idempotent_replay=True)

        started = time.perf_counter()
        try:
            analysis = self.admission_provider.analyze_event(
                role=event.role.value if hasattr(event.role, "value") else str(event.role),
                content=event.content,
                context={
                    "namespace": event.namespace,
                    "user_id": event.user_id,
                    "agent_id": event.agent_id,
                    "session_id": event.session_id,
                },
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

        # Whole-event privacy short-circuit: still record a single redacted IGNORE audit.
        if contains_secret_like_data(event.content).is_sensitive and not analysis.candidates:
            analysis_candidates = []
        else:
            analysis_candidates = analysis.candidates

        # If event is secret-like and provider somehow returned candidates, policy will redact.
        if contains_secret_like_data(event.content).is_sensitive and not analysis_candidates:
            from app.admission.models import (
                AdmissionCandidate,
                CandidateAnalysis,
            )
            from app.models.memory import MemoryType

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

            for decision in decisions:
                memory_id: str | None = None
                if decision.decision == "STORE":
                    memory = self.memory_service.create(
                        MemoryCreate(
                            namespace=event.namespace,
                            user_id=event.user_id,
                            agent_id=event.agent_id,
                            content=decision.candidate.content,
                            memory_type=decision.candidate.memory_type,
                            importance=decision.candidate.importance,
                            confidence=decision.candidate.confidence,
                            source_event_id=event.id,
                            metadata={"admitted_from_event": True},
                        ),
                        commit=False,
                    )
                    memory_id = memory.id

                safe_content = (
                    REDACTED_PLACEHOLDER
                    if decision.redacted
                    else decision.candidate.content
                )
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
                    created_memory_id=memory_id,
                    provider=self.admission_provider.provider_name,
                    model_name=self.admission_provider.model_name,
                )
                self.admission_repo.create(audit, commit=False)
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
                    )
                )

            # Empty analysis → still mark event admitted with zero results? Spec wants
            # idempotency; store a sentinel IGNORE so replay works.
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

        stored = sum(1 for r in results if r.decision == "STORE")
        ignored = sum(1 for r in results if r.decision == "IGNORE")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Admitted event_id=%s candidates=%s stored=%s ignored=%s "
            "provider=%s model=%s duration_ms=%s",
            event_id,
            len(results),
            stored,
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
        *,
        idempotent_replay: bool,
    ) -> AdmitEventResponse:
        results = [
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
            )
            for row in audits
        ]
        return AdmitEventResponse(
            event_id=event_id,
            processed=len(results),
            stored=sum(1 for r in results if r.decision == "STORE"),
            ignored=sum(1 for r in results if r.decision == "IGNORE"),
            results=results,
            idempotent_replay=idempotent_replay,
        )
