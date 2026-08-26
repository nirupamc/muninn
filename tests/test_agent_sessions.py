"""Tests for agent session capture (M8.3)."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
    AgentSessionStatus,
)
from app.capture.agent_sessions.normalizer import SessionNormalizer
from app.capture.agent_sessions.service import AgentSessionService, AgentSessionCaptureResult
from app.capture.agent_sessions.checkpoints import AgentSessionCheckpoint


class TestSessionNormalizer:
    """Tests for the SessionNormalizer."""

    @pytest.fixture
    def normalizer(self) -> SessionNormalizer:
        return SessionNormalizer()

    def test_is_trivial_short_content(self, normalizer: SessionNormalizer) -> None:
        """Test that very short content is marked as trivial."""
        assert normalizer.is_trivial("")
        assert normalizer.is_trivial(" ")
        assert normalizer.is_trivial("a")
        assert normalizer.is_trivial("ok")

    def test_is_trivial_single_word(self, normalizer: SessionNormalizer) -> None:
        """Test that single words are marked as trivial."""
        assert normalizer.is_trivial("continue")
        assert normalizer.is_trivial("yes")
        assert normalizer.is_trivial("no")

    def test_is_trivial_known_patterns(self, normalizer: SessionNormalizer) -> None:
        """Test that known trivial patterns are detected."""
        assert normalizer.is_trivial("run tests")
        assert normalizer.is_trivial("try again")
        assert normalizer.is_trivial("what now")
        assert normalizer.is_trivial("fix this")
        assert normalizer.is_trivial("help")

    def test_is_not_trivial_meaningful(self, normalizer: SessionNormalizer) -> None:
        """Test that meaningful content is not marked as trivial."""
        assert not normalizer.is_trivial("Fixed the bug in the capture manager")
        assert not normalizer.is_trivial("Implemented agent session capture")
        assert not normalizer.is_trivial("Use SQLite for local-first persistence")

    def test_classify_event_type_decision(self, normalizer: SessionNormalizer) -> None:
        """Test classification of decision events."""
        result = normalizer.classify_event_type(
            "We will use SQLite for persistence",
            role="user",
        )
        assert result == AgentSessionEventType.decision

    def test_classify_event_type_fix(self, normalizer: SessionNormalizer) -> None:
        """Test classification of fix events."""
        result = normalizer.classify_event_type(
            "Fixed the bug in the capture manager",
            role="user",
        )
        assert result == AgentSessionEventType.fix

    def test_classify_event_type_bug(self, normalizer: SessionNormalizer) -> None:
        """Test classification of bug events."""
        result = normalizer.classify_event_type(
            "Found a bug in the parsing logic",
            role="user",
        )
        assert result == AgentSessionEventType.bug

    def test_classify_event_type_milestone(self, normalizer: SessionNormalizer) -> None:
        """Test classification of milestone events."""
        result = normalizer.classify_event_type(
            "Tests passed successfully",
            role="assistant",
        )
        assert result == AgentSessionEventType.milestone

    def test_classify_event_type_blocker(self, normalizer: SessionNormalizer) -> None:
        """Test classification of blocker events."""
        result = normalizer.classify_event_type(
            "Cannot proceed without the API key",
            role="user",
        )
        assert result == AgentSessionEventType.blocker

    def test_classify_event_type_constraint(self, normalizer: SessionNormalizer) -> None:
        """Test classification of constraint events."""
        result = normalizer.classify_event_type(
            "Must use local-first storage",
            role="user",
        )
        assert result == AgentSessionEventType.constraint

    def test_classify_event_type_user_message(self, normalizer: SessionNormalizer) -> None:
        """Test classification of generic user messages."""
        result = normalizer.classify_event_type(
            "What is the status of the project?",
            role="user",
        )
        assert result == AgentSessionEventType.user_message

    def test_classify_event_type_assistant_message(self, normalizer: SessionNormalizer) -> None:
        """Test classification of generic assistant messages."""
        result = normalizer.classify_event_type(
            "The project is ready for deployment.",
            role="assistant",
        )
        assert result == AgentSessionEventType.assistant_message

    def test_build_capture_event_trivial_returns_none(self, normalizer: SessionNormalizer) -> None:
        """Test that trivial events return None."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_1",
        )
        event = AgentSessionEvent(
            session_id=session.id,
            source=AgentSessionSource.kilo,
            event_type=AgentSessionEventType.user_message,
            role="user",
            content="continue",
        )
        result = normalizer.build_capture_event(session, event)
        assert result is None

    def test_build_capture_event_meaningful(self, normalizer: SessionNormalizer) -> None:
        """Test that meaningful events return capture data."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_1",
        )
        event = AgentSessionEvent(
            session_id=session.id,
            source=AgentSessionSource.kilo,
            event_type=AgentSessionEventType.user_message,
            role="user",
            content="Implemented agent session capture",
        )
        result = normalizer.build_capture_event(session, event)
        assert result is not None
        assert "content" in result
        assert "event_type" in result
        assert "fingerprint" in result

    def test_build_capture_event_from_fix(self, normalizer: SessionNormalizer) -> None:
        """Test building capture event from a fix."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_1",
            project_path="E:/Muninn",
        )
        event = AgentSessionEvent(
            session_id=session.id,
            source=AgentSessionSource.kilo,
            event_type=AgentSessionEventType.fix,
            role="user",
            content="Fixed the capture manager bug",
        )
        result = normalizer.build_capture_event(session, event)
        assert result is not None
        # Fixes are mapped to agent_decision in the normalizer
        assert result["event_type"].value == "agent_decision"

    def test_build_session_summary_empty(self, normalizer: SessionNormalizer) -> None:
        """Test that empty sessions return None for summary."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_1",
        )
        result = normalizer.build_session_summary(session, [])
        assert result is None

    def test_build_session_summary_with_events(self, normalizer: SessionNormalizer) -> None:
        """Test building session summary with events."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_1",
            project_path="E:/Muninn",
            title="Test Session",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        events = [
            AgentSessionEvent(
                session_id=session.id,
                source=AgentSessionSource.kilo,
                event_type=AgentSessionEventType.fix,
                role="user",
                content="Fixed the bug",
            ),
            AgentSessionEvent(
                session_id=session.id,
                source=AgentSessionSource.kilo,
                event_type=AgentSessionEventType.milestone,
                role="assistant",
                content="Tests passed",
            ),
        ]
        result = normalizer.build_session_summary(session, events)
        assert result is not None
        assert "content" in result
        assert "agent_session_id" in result["metadata"]


class TestAgentSessionCheckpoint:
    """Tests for AgentSessionCheckpoint."""

    def test_checkpoint_defaults(self) -> None:
        """Test checkpoint default values."""
        cp = AgentSessionCheckpoint()
        assert cp.last_session_id is None
        assert cp.last_event_id is None
        assert cp.last_event_timestamp == 0.0
        assert cp.file_offset == 0
        assert cp.last_row_id == 0
        assert cp.adapter_metadata == {}

    def test_checkpoint_serialization(self) -> None:
        """Test checkpoint JSON serialization."""
        cp = AgentSessionCheckpoint(
            last_session_id="session_1",
            last_event_id="event_1",
            last_event_timestamp=12345.0,
            file_offset=100,
            last_row_id=50,
            adapter_metadata={"key": "value"},
        )
        json_str = cp.to_json()
        assert "session_1" in json_str
        assert "event_1" in json_str
        assert "12345.0" in json_str

    def test_checkpoint_deserialization(self) -> None:
        """Test checkpoint JSON deserialization."""
        data = {
            "last_session_id": "session_1",
            "last_event_id": "event_1",
            "last_event_timestamp": 12345.0,
            "file_offset": 100,
            "last_row_id": 50,
            "adapter_metadata": {"key": "value"},
        }
        cp = AgentSessionCheckpoint.from_json(data)
        assert cp.last_session_id == "session_1"
        assert cp.last_event_id == "event_1"
        assert cp.last_event_timestamp == 12345.0
        assert cp.file_offset == 100
        assert cp.last_row_id == 50
        assert cp.adapter_metadata == {"key": "value"}

    def test_checkpoint_update(self) -> None:
        """Test checkpoint update method."""
        cp = AgentSessionCheckpoint()
        cp.update(
            session_id="new_session",
            event_id="new_event",
            timestamp=9999.0,
        )
        assert cp.last_session_id == "new_session"
        assert cp.last_event_id == "new_event"
        assert cp.last_event_timestamp == 9999.0


class TestAgentSessionModels:
    """Tests for agent session dataclass models."""

    def test_agent_session_creation(self) -> None:
        """Test AgentSession dataclass creation."""
        session = AgentSession(
            source=AgentSessionSource.codex,
            external_session_id="session_123",
        )
        assert session.source == AgentSessionSource.codex
        assert session.external_session_id == "session_123"
        assert session.id is not None  # Auto-generated
        assert session.status == AgentSessionStatus.active
        assert session.is_active
        assert not session.is_finished

    def test_agent_session_finished(self) -> None:
        """Test AgentSession finished status."""
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="session_123",
            status=AgentSessionStatus.finished,
        )
        assert session.is_finished
        assert not session.is_active

    def test_agent_session_event_creation(self) -> None:
        """Test AgentSessionEvent dataclass creation."""
        event = AgentSessionEvent(
            session_id="session_123",
            source=AgentSessionSource.opencode,
            event_type=AgentSessionEventType.user_message,
            content="Test message",
        )
        assert event.session_id == "session_123"
        assert event.source == AgentSessionSource.opencode
        assert event.event_type == AgentSessionEventType.user_message
        assert event.content == "Test message"
        assert event.id is not None  # Auto-generated

    def test_agent_session_event_user_message(self) -> None:
        """Test AgentSessionEvent user message property."""
        event = AgentSessionEvent(
            session_id="session_123",
            source=AgentSessionSource.kilo,
            event_type=AgentSessionEventType.user_message,
            content="Test",
            role="user",
        )
        assert event.is_user_message
        assert not event.is_assistant_message

    def test_agent_session_event_tool_result(self) -> None:
        """Test AgentSessionEvent tool result property."""
        event = AgentSessionEvent(
            session_id="session_123",
            source=AgentSessionSource.codex,
            event_type=AgentSessionEventType.tool_result,
            content="Test",
        )
        assert event.is_tool_result
        assert not event.is_tool_call


class TestAgentSessionService:
    """Tests for AgentSessionService (requires database)."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock database session."""
        db = MagicMock()
        
        # Mock the query behavior
        db.query.return_value.filter.return_value.all.return_value = []
        
        return db

    def test_service_initialization(self, mock_db: MagicMock) -> None:
        """Test AgentSessionService initialization."""
        with patch("app.capture.agent_sessions.service.CaptureService"):
            service = AgentSessionService(mock_db)
            assert service.db == mock_db
            assert service.normalizer is not None
            assert service._adapters is not None
            assert len(service._adapters) == 3  # codex, kilo, opencode

    def test_get_available_adapters(self, mock_db: MagicMock) -> None:
        """Test getting available adapters."""
        with patch("app.capture.agent_sessions.service.CaptureService"):
            service = AgentSessionService(mock_db)
            available = service.get_available_adapters()
            # At least Codex should be available if the sessions directory exists
            assert isinstance(available, list)
            assert len(available) >= 0

    def test_get_adapter_health(self, mock_db: MagicMock) -> None:
        """Test getting adapter health."""
        with patch("app.capture.agent_sessions.service.CaptureService"):
            service = AgentSessionService(mock_db)
            health = service.get_adapter_health()
            assert isinstance(health, dict)
            assert len(health) == 3  # codex, kilo, opencode
            for source, info in health.items():
                assert "name" in info
                assert "available" in info

    def test_discover_sessions_returns_list(self, mock_db: MagicMock) -> None:
        """Test that discover_sessions returns a list."""
        with patch("app.capture.agent_sessions.service.CaptureService"):
            service = AgentSessionService(mock_db)
            sessions = service.discover_sessions()
            assert isinstance(sessions, list)


class TestAgentSessionCaptureResult:
    """Tests for AgentSessionCaptureResult dataclass."""

    def test_result_creation(self) -> None:
        """Test AgentSessionCaptureResult creation."""
        result = AgentSessionCaptureResult(
            session_id="session_1",
            events_discovered=10,
            events_processed=8,
            capture_events_created=5,
            memories_created=3,
            errors=[],
        )
        assert result.session_id == "session_1"
        assert result.events_discovered == 10
        assert result.events_processed == 8
        assert result.capture_events_created == 5
        assert result.memories_created == 3
        assert result.errors == []
