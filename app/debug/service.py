"""M13 — Memory debugger service.

Assembles the complete debug view for a memory by joining all
relevant trace tables. Read-only — never mutates memory state,
never reinforces, never updates last_accessed, never creates
retrieval events.

Key invariant: debugger reads history, debugger does NOT change history.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.debug.schemas import (
    DebugAdmission,
    DebugDedup,
    DebugMemoryIdentity,
    DebugMemoryView,
    DebugObservationView,
    DebugProvenance,
    DebugReinforcement,
    DebugRepresentations,
    DebugSourceEvent,
    DebugTemporal,
    DebugTimelineEntry,
)
from app.memory.representations.service import RepresentationService
from app.models.admission import MemoryAdmission
from app.models.capture import CaptureEvent
from app.models.deduplication import MemoryDeduplicationDecision, MemoryReinforcement
from app.models.memory import Memory
from app.models.temporal import MemoryTemporalDecision

logger = logging.getLogger("munin.debug")

# Content preview length for observation views
_CONTENT_PREVIEW_LENGTH = 200

# Max results for timeline / source events
_MAX_TIMELINE = 50
_MAX_SOURCE_EVENTS = 20


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (words * 1.3)."""
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


def _safe_preview(content: str | None, max_len: int = _CONTENT_PREVIEW_LENGTH) -> str:
    """Truncate content for display, never raise."""
    if not content:
        return ""
    if len(content) <= max_len:
        return content
    return content[:max_len] + "..."


class DebugService:
    """Assembles debug views from existing trace tables.

    All methods are read-only. No side effects on memory state.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_memory_debug(self, memory_id: str) -> DebugMemoryView | None:
        """Build the complete debug view for one memory.

        Returns None if memory not found. Never raises 500 for
        missing trace data — returns null/empty sections instead.
        """
        memory = self.db.query(Memory).filter(Memory.id == memory_id).first()
        if memory is None:
            return None

        # Identity
        identity = DebugMemoryIdentity(
            memory_id=memory.id,
            namespace=memory.namespace,
            memory_type=memory.memory_type.value,
            status=memory.status.value,
            importance=memory.importance,
            confidence=memory.confidence,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
        )

        # Representations
        representations = self._build_representations(memory)

        # Provenance
        provenance = self._build_provenance(memory)

        # Admission trace
        admission = self._build_admission_trace(memory)

        # Dedup / reinforcement
        dedup, reinforcements, reinforcement_count = self._build_dedup_trace(memory)

        # Temporal
        temporal = self._build_temporal_trace(memory)

        # Source events
        source_events = self._build_source_events(memory)

        return DebugMemoryView(
            identity=identity,
            representations=representations,
            provenance=provenance,
            admission=admission,
            dedup=dedup,
            reinforcements=reinforcements,
            reinforcement_count=reinforcement_count,
            temporal=temporal,
            source_events=source_events,
        )

    def get_observation_debug(self, capture_event_id: str) -> DebugObservationView | None:
        """Debug view for one capture event / observation.

        Returns None if not found.
        """
        event = self.db.query(CaptureEvent).filter(CaptureEvent.id == capture_event_id).first()
        if event is None:
            return None

        meta = event.metadata_ or {}
        return DebugObservationView(
            capture_event_id=event.id,
            source=event.source.value if hasattr(event.source, "value") else str(event.source),
            event_type=event.source_event_type.value
            if hasattr(event.source_event_type, "value")
            else str(event.source_event_type),
            namespace=event.namespace,
            agent_id=event.agent_id,
            session_id=event.session_id,
            observation_type=meta.get("observation_type"),
            observation_id=meta.get("observation_id"),
            content_preview=_safe_preview(event.content),
            admission_decision=event.admission_decision.value
            if event.admission_decision and hasattr(event.admission_decision, "value")
            else (event.admission_decision if isinstance(event.admission_decision, str) else None),
            memory_id=event.memory_id,
            occurred_at=event.occurred_at,
            captured_at=event.captured_at,
            metadata=_sanitize_metadata(meta),
        )

    def get_recent_timeline(
        self,
        namespace: str | None = None,
        limit: int = _MAX_TIMELINE,
    ) -> list[DebugTimelineEntry]:
        """Bounded recent debug timeline derived from persisted records.

        Reads from capture_events + memory_admissions. Never creates new records.
        """
        query = self.db.query(CaptureEvent)
        if namespace:
            query = query.filter(CaptureEvent.namespace == namespace)
        query = query.order_by(CaptureEvent.occurred_at.desc()).limit(min(limit * 2, 200))

        events = query.all()
        entries: list[DebugTimelineEntry] = []

        for event in events:
            meta = event.metadata_ or {}
            obs_type = meta.get("observation_type", "unknown")

            # Determine event label
            if event.admission_decision:
                decision_val = (
                    event.admission_decision.value
                    if hasattr(event.admission_decision, "value")
                    else str(event.admission_decision)
                )
                if decision_val == "STORE":
                    label = "STORED"
                elif decision_val == "IGNORE":
                    label = "IGNORED"
                else:
                    label = decision_val
            else:
                label = "OBSERVED"

            details: dict[str, Any] = {}
            if obs_type and obs_type != "unknown":
                details["observation_type"] = obs_type
            if event.memory_id:
                details["memory_id"] = event.memory_id
            if meta.get("agent_host"):
                details["agent_host"] = meta["agent_host"]
            if meta.get("model"):
                details["model"] = meta["model"]

            entries.append(
                DebugTimelineEntry(
                    timestamp=event.occurred_at,
                    event_type=label,
                    source=event.source.value if hasattr(event.source, "value") else str(event.source),
                    namespace=event.namespace,
                    memory_id=event.memory_id,
                    content_preview=_safe_preview(event.content, 100),
                    details=details,
                )
            )

            if len(entries) >= limit:
                break

        return entries

    # ------------------------------------------------------------------
    # Private builders — all read-only
    # ------------------------------------------------------------------

    def _build_representations(self, memory: Memory) -> DebugRepresentations:
        """Build L0/L1/L2 representation data with token costs."""
        content = memory.content or ""
        gist = memory.gist
        summary = memory.summary

        available: list[str] = ["L2"]
        if gist:
            available.insert(0, "L0")
        if summary:
            available.insert(1 if "L0" in available else 0, "L1")

        return DebugRepresentations(
            l0_gist=gist,
            l1_summary=summary,
            l2_content=content,
            l0_token_cost=_estimate_tokens(gist) if gist else 0,
            l1_token_cost=_estimate_tokens(summary) if summary else 0,
            l2_token_cost=_estimate_tokens(content),
            available_levels=available,
        )

    def _build_provenance(self, memory: Memory) -> DebugProvenance:
        """Build provenance data from capture events."""
        meta = memory.metadata_ or {}

        # Try to find the originating capture event
        source_event_id = memory.source_event_id
        capture_event_id: str | None = None
        agent_host: str | None = None
        model: str | None = None
        session_id: str | None = None
        observation_type: str | None = None
        observation_id: str | None = None
        source_name: str | None = None
        timestamp: Any = None

        if source_event_id:
            # Try CaptureEvent first
            cap_event = self.db.query(CaptureEvent).filter(CaptureEvent.id == source_event_id).first()
            if cap_event:
                capture_event_id = cap_event.id
                event_meta = cap_event.metadata_ or {}
                agent_host = event_meta.get("agent_host") or cap_event.agent_id
                model = event_meta.get("model")
                session_id = event_meta.get("session_id") or cap_event.session_id
                observation_type = event_meta.get("observation_type")
                observation_id = event_meta.get("observation_id")
                source_name = cap_event.source.value if hasattr(cap_event.source, "value") else str(cap_event.source)
                timestamp = cap_event.occurred_at
            else:
                # Fallback: source_event_id references events.id
                from app.models.event import Event
                evt = self.db.query(Event).filter(Event.id == source_event_id).first()
                if evt:
                    evt_meta = evt.metadata_ or {}
                    agent_host = evt_meta.get("agent_host") or evt.agent_id
                    model = evt_meta.get("model")
                    session_id = evt_meta.get("session_id") or evt.session_id
                    observation_type = evt_meta.get("observation_type")
                    observation_id = evt_meta.get("observation_id")
                    source_name = "event"
                    timestamp = evt.created_at

        # Fallback to memory-level metadata
        if not agent_host:
            agent_host = meta.get("agent_host")
        if not model:
            model = meta.get("model")
        if not session_id:
            session_id = meta.get("session_id")

        return DebugProvenance(
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            observation_type=observation_type,
            observation_id=observation_id,
            capture_event_id=capture_event_id,
            source=source_name or meta.get("source"),
            source_event_id=source_event_id,
            timestamp=timestamp,
        )

    def _build_admission_trace(self, memory: Memory) -> DebugAdmission | None:
        """Find the admission decision for this memory.

        Looks up by created_memory_id on memory_admissions.
        """
        admission = (
            self.db.query(MemoryAdmission)
            .filter(MemoryAdmission.created_memory_id == memory.id)
            .order_by(MemoryAdmission.created_at.desc())
            .first()
        )
        if admission is None:
            return None

        return DebugAdmission(
            decision=admission.decision,
            admission_score=admission.admission_score,
            importance=admission.importance,
            confidence=admission.confidence,
            future_utility=admission.future_utility,
            stability=admission.stability,
            specificity=admission.specificity,
            explicitness=admission.explicitness,
            triviality=admission.triviality,
            reason_codes=list(admission.reason_codes or []),
            provider=admission.provider,
            model_name=admission.model_name,
            created_at=admission.created_at,
        )

    def _build_dedup_trace(
        self, memory: Memory
    ) -> tuple[DebugDedup | None, list[DebugReinforcement], int]:
        """Build dedup and reinforcement trace."""
        # Find dedup decision that created this memory
        dedup_row = (
            self.db.query(MemoryDeduplicationDecision)
            .filter(MemoryDeduplicationDecision.created_memory_id == memory.id)
            .order_by(MemoryDeduplicationDecision.created_at.desc())
            .first()
        )

        dedup: DebugDedup | None = None
        if dedup_row:
            dedup = DebugDedup(
                relationship=dedup_row.relationship,
                matched_memory_id=dedup_row.matched_memory_id,
                relationship_confidence=dedup_row.relationship_confidence,
                similarity_score=dedup_row.similarity_score,
                reason_codes=list(dedup_row.reason_codes or []),
                created_new_memory=True,
            )

        # Find reinforcements FOR this memory (it was reinforced, not the other way)
        reinforcement_rows = (
            self.db.query(MemoryReinforcement)
            .filter(MemoryReinforcement.memory_id == memory.id)
            .order_by(MemoryReinforcement.created_at.desc())
            .all()
        )

        reinforcements = [
            DebugReinforcement(
                source_event_id=row.source_event_id,
                candidate_content=_safe_preview(row.candidate_content, 300),
                relationship_confidence=row.relationship_confidence,
                created_at=row.created_at,
            )
            for row in reinforcement_rows
        ]

        return dedup, reinforcements, len(reinforcement_rows)

    def _build_temporal_trace(self, memory: Memory) -> list[DebugTemporal]:
        """Build temporal relationship history."""
        rows = (
            self.db.query(MemoryTemporalDecision)
            .filter(
                (MemoryTemporalDecision.created_memory_id == memory.id)
                | (MemoryTemporalDecision.matched_memory_id == memory.id)
            )
            .order_by(MemoryTemporalDecision.created_at.desc())
            .all()
        )

        return [
            DebugTemporal(
                relationship=row.relationship,
                matched_memory_id=row.matched_memory_id,
                created_memory_id=row.created_memory_id,
                relationship_confidence=row.relationship_confidence,
                similarity_score=row.similarity_score,
                old_status=row.old_status,
                new_old_status=row.new_old_status,
                old_valid_until_before=row.old_valid_until_before,
                old_valid_until_after=row.old_valid_until_after,
                new_valid_from=row.new_valid_from,
                reason_codes=list(row.reason_codes or []),
            )
            for row in rows
        ]

    def _build_source_events(self, memory: Memory) -> list[DebugSourceEvent]:
        """Find capture events that relate to this memory."""
        # Direct source event
        direct_events: list[CaptureEvent] = []
        if memory.source_event_id:
            event = self.db.query(CaptureEvent).filter(CaptureEvent.id == memory.source_event_id).first()
            if event:
                direct_events.append(event)

        # Also find events where this memory was created
        memory_events = (
            self.db.query(CaptureEvent)
            .filter(CaptureEvent.memory_id == memory.id)
            .order_by(CaptureEvent.occurred_at.desc())
            .limit(_MAX_SOURCE_EVENTS)
            .all()
        )

        seen_ids: set[str] = set()
        results: list[DebugSourceEvent] = []
        for event in direct_events + memory_events:
            if event.id in seen_ids:
                continue
            seen_ids.add(event.id)

            meta = event.metadata_ or {}
            results.append(
                DebugSourceEvent(
                    capture_event_id=event.id,
                    source=event.source.value if hasattr(event.source, "value") else str(event.source),
                    event_type=event.source_event_type.value
                    if hasattr(event.source_event_type, "value")
                    else str(event.source_event_type),
                    agent_id=event.agent_id,
                    session_id=event.session_id,
                    observation_type=meta.get("observation_type"),
                    observation_id=meta.get("observation_id"),
                    content_preview=_safe_preview(event.content),
                    admission_decision=event.admission_decision.value
                    if event.admission_decision and hasattr(event.admission_decision, "value")
                    else (event.admission_decision if isinstance(event.admission_decision, str) else None),
                    occurred_at=event.occurred_at,
                    metadata=_sanitize_metadata(meta),
                )
            )

        return results[:_MAX_SOURCE_EVENTS]


def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from metadata for safe API exposure.

    Never expose: raw secrets, API keys, passwords, tokens.
    """
    sensitive_keys = {
        "api_key",
        "password",
        "token",
        "secret",
        "authorization",
        "private_key",
    }
    return {
        k: v
        for k, v in meta.items()
        if not any(s in k.lower() for s in sensitive_keys)
    }
