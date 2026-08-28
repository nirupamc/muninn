"""M13 — Memory debugger tests.

Tests the debug service and API endpoints for memory explainability.
All tests use isolated in-memory SQLite databases.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.models.capture import (
    CaptureEvent,
    CaptureSource,
    CaptureEventType,
    CaptureProcessingStatus,
)
from app.models.admission import MemoryAdmission
from app.models.deduplication import MemoryDeduplicationDecision, MemoryReinforcement
from app.models.temporal import MemoryTemporalDecision
from app.models.project import Project, ProjectStatus
from app.debug.service import DebugService, _sanitize_metadata, _estimate_tokens


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """Isolated in-memory SQLite session for each test."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=eng)
    TestingSessionLocal = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


def _create_project(session, project_id="proj-1", namespace="project:muninn") -> Project:
    """Helper to create a project record for FK constraints."""
    project = Project(
        id=project_id,
        name=namespace.split(":")[1] if ":" in namespace else namespace,
        namespace=namespace,
        root_path=f"E:\\{namespace.split(':')[1] if ':' in namespace else namespace}",
        canonical_path=f"e:\\{namespace.split(':')[1] if ':' in namespace else namespace}",
        status=ProjectStatus.active,
    )
    session.add(project)
    session.commit()
    return project


def _create_memory(session, **overrides) -> Memory:
    """Helper to create a memory with defaults."""
    defaults = {
        "namespace": "project:muninn",
        "content": "Implemented hybrid retrieval with RRF fusion.",
        "gist": "Implemented hybrid retrieval with RRF fusion.",
        "summary": "Hybrid retrieval combining dense, lexical BM25, graph, and RRF.",
        "memory_type": MemoryType.decision,
        "importance": 0.8,
        "confidence": 0.9,
        "status": MemoryStatus.active,
    }
    defaults.update(overrides)
    memory = Memory(**defaults)
    session.add(memory)
    session.commit()
    return memory


def _create_capture_event(session, memory_id=None, project_id="proj-1", **overrides) -> CaptureEvent:
    """Helper to create a capture event."""
    # Ensure project exists for FK
    existing = session.query(Project).filter(Project.id == project_id).first()
    if not existing:
        _create_project(session, project_id=project_id, namespace=overrides.get("namespace", "project:muninn"))
    defaults = {
        "project_id": project_id,
        "namespace": "project:muninn",
        "source": CaptureSource.codex,
        "source_event_type": CaptureEventType.agent_summary,
        "content": "Implemented hybrid retrieval; 46 tests passed.",
        "fingerprint": "fp-test-123",
        "occurred_at": datetime.now(UTC),
        "processing_status": CaptureProcessingStatus.completed,
        "metadata_": {},
    }
    defaults.update(overrides)
    if memory_id:
        defaults["memory_id"] = memory_id
    # Ensure unique fingerprint per event
    if "fingerprint" in defaults:
        import uuid as _uuid
        defaults["fingerprint"] = f"{defaults['fingerprint']}-{_uuid.uuid4().hex[:8]}"
    event = CaptureEvent(**defaults)
    session.add(event)
    session.commit()
    return event


def _create_event(session, event_id="evt-1", **overrides):
    """Helper to create an Event (for admission/dedup FK constraints)."""
    from app.models.event import Event, EventRole
    defaults = {
        "id": event_id,
        "namespace": "project:muninn",
        "role": EventRole.user,
        "content": "Test event",
    }
    defaults.update(overrides)
    evt = Event(**defaults)
    session.add(evt)
    session.commit()
    return evt


def _create_admission(session, event_id, memory_id=None, **overrides) -> MemoryAdmission:
    """Helper to create an admission record."""
    defaults = {
        "event_id": event_id,
        "candidate_content": "Implemented hybrid retrieval with RRF fusion.",
        "memory_type": "decision",
        "decision": "STORE",
        "admission_score": 0.85,
        "importance": 0.8,
        "confidence": 0.9,
        "reason_codes": ["EXPLICIT_DECISION", "HIGH_FUTURE_UTILITY"],
        "provider": "test-provider",
        "model_name": "test-model",
    }
    defaults.update(overrides)
    if memory_id:
        defaults["created_memory_id"] = memory_id
    admission = MemoryAdmission(**defaults)
    session.add(admission)
    session.commit()
    return admission


def _create_dedup(session, event_id, memory_id=None, **overrides) -> MemoryDeduplicationDecision:
    """Helper to create a dedup decision."""
    defaults = {
        "event_id": event_id,
        "candidate_content": "Implemented hybrid retrieval with RRF fusion.",
        "candidate_memory_type": "decision",
        "relationship": "NEW",
        "relationship_confidence": 0.95,
        "reason_codes": [],
        "provider": "test-provider",
        "model_name": "test-model",
    }
    defaults.update(overrides)
    if memory_id:
        defaults["created_memory_id"] = memory_id
    dedup = MemoryDeduplicationDecision(**defaults)
    session.add(dedup)
    session.commit()
    return dedup


def _create_temporal(session, event_id, created_memory_id=None, **overrides) -> MemoryTemporalDecision:
    """Helper to create a temporal decision."""
    defaults = {
        "event_id": event_id,
        "candidate_content": "Implemented hybrid retrieval with RRF fusion.",
        "candidate_memory_type": "decision",
        "relationship": "NEW",
        "relationship_confidence": 0.9,
        "reason_codes": [],
        "provider": "test-provider",
        "model_name": "test-model",
    }
    defaults.update(overrides)
    if created_memory_id:
        defaults["created_memory_id"] = created_memory_id
    temporal = MemoryTemporalDecision(**defaults)
    session.add(temporal)
    session.commit()
    return temporal


def _create_reinforcement(session, memory_id, event_id, **overrides) -> MemoryReinforcement:
    """Helper to create a reinforcement record."""
    defaults = {
        "memory_id": memory_id,
        "source_event_id": event_id,
        "candidate_content": "Confirmed hybrid retrieval works.",
        "relationship_confidence": 0.88,
        "provider": "test-provider",
        "model_name": "test-model",
    }
    defaults.update(overrides)
    reinforcement = MemoryReinforcement(**defaults)
    session.add(reinforcement)
    session.commit()
    return reinforcement


# -------------------------------------------------------------------
# Tests: Debug Service
# -------------------------------------------------------------------

class TestDebugServiceMemoryView:
    """Tests for DebugService.get_memory_debug."""

    def test_returns_none_for_missing_memory(self, db_session):
        svc = DebugService(db_session)
        result = svc.get_memory_debug("nonexistent-id")
        assert result is None

    def test_identity_panel(self, db_session):
        memory = _create_memory(db_session)
        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.identity.memory_id == memory.id
        assert result.identity.namespace == "project:muninn"
        assert result.identity.memory_type == "decision"
        assert result.identity.status == "active"
        assert result.identity.importance == 0.8
        assert result.identity.confidence == 0.9

    def test_representations_panel(self, db_session):
        memory = _create_memory(db_session)
        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.representations.l0_gist is not None
        assert result.representations.l1_summary is not None
        assert result.representations.l2_content == memory.content
        assert result.representations.l0_token_cost > 0
        assert result.representations.l1_token_cost > 0
        assert result.representations.l2_token_cost > 0
        assert "L0" in result.representations.available_levels
        assert "L1" in result.representations.available_levels
        assert "L2" in result.representations.available_levels

    def test_representations_without_gist_summary(self, db_session):
        memory = _create_memory(db_session, gist=None, summary=None)
        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.representations.l0_gist is None
        assert result.representations.l1_summary is None
        assert result.representations.l0_token_cost == 0
        assert result.representations.l1_token_cost == 0
        assert "L0" not in result.representations.available_levels
        assert "L1" not in result.representations.available_levels
        assert "L2" in result.representations.available_levels

    def test_provenance_from_source_event(self, db_session):
        memory = _create_memory(db_session)
        _create_event(db_session, event_id="evt-src", namespace="project:muninn")
        # source_event_id FK references events.id, not capture_events.id
        memory.source_event_id = "evt-src"
        db_session.commit()

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.provenance.source_event_id == "evt-src"
        # Event metadata fallback — source comes from Event table
        assert result.provenance.capture_event_id is None

    def test_admission_trace(self, db_session):
        memory = _create_memory(db_session)
        _create_event(db_session, event_id="evt-1")
        _create_admission(db_session, "evt-1", memory_id=memory.id)

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.admission is not None
        assert result.admission.decision == "STORE"
        assert result.admission.admission_score == 0.85
        assert "EXPLICIT_DECISION" in result.admission.reason_codes

    def test_admission_trace_none_when_missing(self, db_session):
        memory = _create_memory(db_session)
        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.admission is None

    def test_dedup_trace(self, db_session):
        memory = _create_memory(db_session)
        _create_event(db_session, event_id="evt-2")
        _create_dedup(db_session, "evt-2", memory_id=memory.id)

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.dedup is not None
        assert result.dedup.relationship == "NEW"
        assert result.dedup.created_new_memory is True

    def test_reinforcement_trace(self, db_session):
        memory = _create_memory(db_session)
        _create_event(db_session, event_id="evt-3")
        _create_reinforcement(db_session, memory.id, "evt-3")

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.reinforcement_count == 1
        assert len(result.reinforcements) == 1
        assert result.reinforcements[0].source_event_id == "evt-3"

    def test_temporal_trace(self, db_session):
        memory = _create_memory(db_session)
        _create_event(db_session, event_id="evt-4")
        _create_temporal(
            db_session,
            "evt-4",
            created_memory_id=memory.id,
            relationship="NEW",
        )

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert len(result.temporal) == 1
        assert result.temporal[0].relationship == "NEW"

    def test_source_events(self, db_session):
        memory = _create_memory(db_session)
        event = _create_capture_event(db_session, memory_id=memory.id)

        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert len(result.source_events) >= 1
        assert result.source_events[0].capture_event_id == event.id

    def test_historical_memory_with_missing_traces(self, db_session):
        """Old memory without trace data should not crash."""
        memory = _create_memory(db_session, gist=None, summary=None)
        # No capture event, no admission, no dedup, no temporal
        svc = DebugService(db_session)
        result = svc.get_memory_debug(memory.id)

        assert result is not None
        assert result.identity.memory_id == memory.id
        assert result.admission is None
        assert result.dedup is None
        assert result.reinforcement_count == 0
        assert len(result.temporal) == 0
        assert len(result.source_events) == 0


class TestDebugServiceObservationView:
    """Tests for DebugService.get_observation_debug."""

    def test_returns_none_for_missing_event(self, db_session):
        svc = DebugService(db_session)
        result = svc.get_observation_debug("nonexistent")
        assert result is None

    def test_observation_view_basic(self, db_session):
        event = _create_capture_event(
            db_session,
            metadata_={"observation_type": "decision", "observation_id": "obs-1"},
        )
        svc = DebugService(db_session)
        result = svc.get_observation_debug(event.id)

        assert result is not None
        assert result.capture_event_id == event.id
        assert result.observation_type == "decision"
        assert result.observation_id == "obs-1"
        assert result.admission_decision is None  # No admission yet

    def test_secret_metadata_sanitized(self, db_session):
        event = _create_capture_event(
            db_session,
            metadata_={
                "api_key": "sk-secret-123",
                "password": "hunter2",
                "model": "gpt-5.5",
                "observation_type": "test_result",
            },
        )
        svc = DebugService(db_session)
        result = svc.get_observation_debug(event.id)

        assert result is not None
        assert "api_key" not in result.metadata
        assert "password" not in result.metadata
        assert result.metadata.get("model") == "gpt-5.5"


class TestDebugServiceTimeline:
    """Tests for DebugService.get_recent_timeline."""

    def test_empty_timeline(self, db_session):
        svc = DebugService(db_session)
        result = svc.get_recent_timeline()
        assert result == []

    def test_timeline_with_events(self, db_session):
        _create_capture_event(db_session, content="Test result: 46 passed")
        _create_capture_event(db_session, content="Decision: keep hybrid opt-in")

        svc = DebugService(db_session)
        result = svc.get_recent_timeline()

        assert len(result) == 2
        assert all(e.event_type == "OBSERVED" for e in result)  # No admission yet

    def test_timeline_respects_limit(self, db_session):
        for i in range(10):
            _create_capture_event(db_session, content=f"Event {i}")

        svc = DebugService(db_session)
        result = svc.get_recent_timeline(limit=3)

        assert len(result) == 3

    def test_timeline_namespace_filter(self, db_session):
        _create_capture_event(db_session, namespace="project:muninn")
        _create_capture_event(db_session, namespace="project:huginn")

        svc = DebugService(db_session)
        result = svc.get_recent_timeline(namespace="project:muninn")

        assert len(result) == 1
        assert result[0].namespace == "project:muninn"


# -------------------------------------------------------------------
# Tests: Utility Functions
# -------------------------------------------------------------------

class TestUtilityFunctions:
    def test_estimate_tokens_empty(self):
        assert _estimate_tokens("") == 0
        assert _estimate_tokens(None) == 0

    def test_estimate_tokens_normal(self):
        result = _estimate_tokens("hello world foo bar")
        assert result > 0
        assert result < 20

    def test_sanitize_metadata_removes_secrets(self):
        meta = {"api_key": "sk-123", "password": "x", "model": "gpt-5.5", "token": "abc"}
        result = _sanitize_metadata(meta)
        assert "api_key" not in result
        assert "password" not in result
        assert "token" not in result
        assert result["model"] == "gpt-5.5"

    def test_sanitize_metadata_preserves_normal(self):
        meta = {"observation_type": "test_result", "agent_host": "codex", "count": 42}
        result = _sanitize_metadata(meta)
        assert result == meta


# -------------------------------------------------------------------
# Tests: No Side Effects Invariant
# -------------------------------------------------------------------

class TestNoSideEffects:
    """Debugger reads should never change memory state."""

    def test_debug_read_does_not_update_last_accessed(self, db_session):
        memory = _create_memory(db_session)
        original_accessed = memory.last_accessed_at

        svc = DebugService(db_session)
        svc.get_memory_debug(memory.id)

        db_session.refresh(memory)
        assert memory.last_accessed_at == original_accessed

    def test_debug_read_does_not_change_importance(self, db_session):
        memory = _create_memory(db_session, importance=0.8)
        original_importance = memory.importance

        svc = DebugService(db_session)
        svc.get_memory_debug(memory.id)

        db_session.refresh(memory)
        assert memory.importance == original_importance

    def test_observation_debug_does_not_modify_event(self, db_session):
        event = _create_capture_event(db_session)
        original_content = event.content

        svc = DebugService(db_session)
        svc.get_observation_debug(event.id)

        db_session.refresh(event)
        assert event.content == original_content


# -------------------------------------------------------------------
# Tests: Namespace Isolation
# -------------------------------------------------------------------

class TestNamespaceIsolation:
    """Debug views must respect namespace boundaries."""

    def test_timeline_filters_by_namespace(self, db_session):
        _create_capture_event(db_session, namespace="project:muninn")
        _create_capture_event(db_session, namespace="project:huginn")
        _create_capture_event(db_session, namespace="project:muninn")

        svc = DebugService(db_session)
        result = svc.get_recent_timeline(namespace="project:muninn")

        assert len(result) == 2
        assert all(e.namespace == "project:muninn" for e in result)
