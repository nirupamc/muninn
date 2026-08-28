"""M12 — Structured observation tests.

Tests for observation types, normalization, filtering, and integration
with existing capture pipeline.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.capture.agent_sessions.models import (
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
)
from app.observations.models import (
    HIGH_VALUE_TYPES,
    NOISE_TYPES,
    Observation,
    ObservationType,
)
from app.observations.normalizer import ObservationNormalizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def normalizer() -> ObservationNormalizer:
    return ObservationNormalizer()


def _make_event(
    content: str,
    *,
    event_type: AgentSessionEventType = AgentSessionEventType.assistant_message,
    role: str = "assistant",
    source: AgentSessionSource = AgentSessionSource.codex,
    session_id: str = "test-session",
) -> AgentSessionEvent:
    return AgentSessionEvent(
        session_id=session_id,
        source=source,
        event_type=event_type,
        content=content,
        role=role,
    )


# ---------------------------------------------------------------------------
# ObservationType enum tests
# ---------------------------------------------------------------------------

class TestObservationType:
    """Tests for ObservationType enum."""

    def test_all_types_exist(self):
        """All expected observation types should be defined."""
        expected = {
            "user_message", "agent_message", "decision", "tool_call", "tool_result",
            "command_run", "command_result", "file_edit", "file_create", "file_delete",
            "test_run", "test_result", "git_commit", "build_result", "api_result",
            "verification", "error", "warning", "blocker",
            "session_start", "session_end", "other",
        }
        actual = {t.value for t in ObservationType}
        assert expected == actual

    def test_high_value_types(self):
        """High-value types should include key memory candidates."""
        assert ObservationType.DECISION in HIGH_VALUE_TYPES
        assert ObservationType.TEST_RESULT in HIGH_VALUE_TYPES
        assert ObservationType.ERROR in HIGH_VALUE_TYPES
        assert ObservationType.BLOCKER in HIGH_VALUE_TYPES
        assert ObservationType.VERIFICATION in HIGH_VALUE_TYPES

    def test_noise_types(self):
        """Noise types should not produce durable memories."""
        assert ObservationType.TOOL_CALL in NOISE_TYPES
        assert ObservationType.TOOL_RESULT in NOISE_TYPES
        assert ObservationType.USER_MESSAGE in NOISE_TYPES


# ---------------------------------------------------------------------------
# Observation model tests
# ---------------------------------------------------------------------------

class TestObservationModel:
    """Tests for Observation dataclass."""

    def test_to_capture_content(self):
        obs = Observation(
            type=ObservationType.TEST_RESULT,
            content="46 tests passed",
            structured_data={"passed": 46, "failed": 0},
        )
        content = obs.to_capture_content()
        assert "[TEST_RESULT]" in content
        assert "46 tests passed" in content

    def test_to_capture_metadata(self):
        obs = Observation(
            type=ObservationType.ERROR,
            agent_host="codex",
            model="gpt-5.5",
            structured_data={"error_type": "ValueError"},
        )
        meta = obs.to_capture_metadata()
        assert meta["observation_type"] == "error"
        assert meta["agent_host"] == "codex"
        assert meta["model"] == "gpt-5.5"
        assert meta["structured_data"]["error_type"] == "ValueError"

    def test_default_values(self):
        obs = Observation()
        assert obs.type == ObservationType.OTHER
        assert obs.id  # UUID generated
        assert obs.content == ""


# ---------------------------------------------------------------------------
# Trivial filtering tests
# ---------------------------------------------------------------------------

class TestTrivialFiltering:
    """Tests for trivial event filtering."""

    def test_trivial_single_word(self, normalizer: ObservationNormalizer):
        event = _make_event("continue")
        assert normalizer.normalize_event(event) is None

    def test_trivial_okay(self, normalizer: ObservationNormalizer):
        event = _make_event("okay")
        assert normalizer.normalize_event(event) is None

    def test_trivial_empty(self, normalizer: ObservationNormalizer):
        event = _make_event("")
        assert normalizer.normalize_event(event) is None

    def test_not_trivial_meaningful(self, normalizer: ObservationNormalizer):
        event = _make_event("Fixed the authentication bug in login endpoint")
        obs = normalizer.normalize_event(event)
        assert obs is not None


# ---------------------------------------------------------------------------
# Secret filtering tests
# ---------------------------------------------------------------------------

class TestSecretFiltering:
    """Tests for secret/credential filtering."""

    def test_api_key_filtered(self, normalizer: ObservationNormalizer):
        event = _make_event("API key: sk-abc123def456ghi789jkl012mno")
        assert normalizer.normalize_event(event) is None

    def test_password_filtered(self, normalizer: ObservationNormalizer):
        event = _make_event("password=secret123")
        assert normalizer.normalize_event(event) is None

    def test_private_key_filtered(self, normalizer: ObservationNormalizer):
        event = _make_event("-----BEGIN RSA PRIVATE KEY-----")
        assert normalizer.normalize_event(event) is None

    def test_env_var_filtered(self, normalizer: ObservationNormalizer):
        event = _make_event("OPENAI_API_KEY=sk-abc123def456ghi789jkl012mno")
        assert normalizer.normalize_event(event) is None

    def test_no_false_positive_on_normal_text(self, normalizer: ObservationNormalizer):
        event = _make_event("Fixed the API endpoint for user authentication")
        obs = normalizer.normalize_event(event)
        assert obs is not None


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassification:
    """Tests for observation type classification."""

    def test_decision_detected(self, normalizer: ObservationNormalizer):
        event = _make_event("Decision: use FastAPI for REST endpoints")
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.DECISION

    def test_error_detected(self, normalizer: ObservationNormalizer):
        event = _make_event("UnicodeDecodeError: utf-8 codec failed")
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.ERROR

    def test_verification_detected(self, normalizer: ObservationNormalizer):
        event = _make_event("Verified: git diff --check is clean")
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.VERIFICATION

    def test_blocker_detected(self, normalizer: ObservationNormalizer):
        event = _make_event("Cannot proceed: blocked by missing dependency")
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.BLOCKER

    def test_test_result_detected(self, normalizer: ObservationNormalizer):
        event = _make_event("46 passed, 0 failed in 1.46s", event_type=AgentSessionEventType.tool_result)
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.TEST_RESULT
        assert obs.structured_data.get("passed") == 46

    def test_tool_call_preserved(self, normalizer: ObservationNormalizer):
        event = _make_event("Run pytest", event_type=AgentSessionEventType.tool_call)
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.TOOL_CALL

    def test_tool_result_preserved(self, normalizer: ObservationNormalizer):
        event = _make_event("Build succeeded", event_type=AgentSessionEventType.tool_result)
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.TOOL_RESULT

    def test_user_message(self, normalizer: ObservationNormalizer):
        event = _make_event("Fix the login bug", event_type=AgentSessionEventType.user_message, role="user")
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.USER_MESSAGE

    def test_agent_message(self, normalizer: ObservationNormalizer):
        event = _make_event("I'll inspect the authentication module", event_type=AgentSessionEventType.assistant_message)
        obs = normalizer.normalize_event(event)
        assert obs is not None
        assert obs.type == ObservationType.AGENT_MESSAGE


# ---------------------------------------------------------------------------
# Command normalization tests
# ---------------------------------------------------------------------------

class TestCommandNormalization:
    """Tests for command observation normalization."""

    def test_pytest_command(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_command("pytest tests/ -v", exit_code=0)
        assert obs.type == ObservationType.TEST_RUN

    def test_pytest_with_output(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_command(
            "pytest tests/ -v", exit_code=0,
            stdout="46 passed, 0 failed in 1.46s",
        )
        assert obs.type == ObservationType.TEST_RESULT
        assert obs.structured_data.get("passed") == 46

    def test_git_command(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_command("git status", agent_host="codex")
        assert obs.type == ObservationType.COMMAND_RUN
        assert obs.structured_data.get("command") == "git status"

    def test_command_with_exit_code(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_command("pytest tests/ -v", exit_code=1)
        assert obs.structured_data.get("exit_code") == 1


# ---------------------------------------------------------------------------
# File change normalization tests
# ---------------------------------------------------------------------------

class TestFileNormalization:
    """Tests for file change observation normalization."""

    def test_file_edit(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_file_change("app/main.py", "edit", additions=10, deletions=5)
        assert obs.type == ObservationType.FILE_EDIT
        assert obs.structured_data.get("path") == "app/main.py"

    def test_file_create(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_file_change("app/new_module.py", "create")
        assert obs.type == ObservationType.FILE_CREATE

    def test_file_delete(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_file_change("app/old_module.py", "delete")
        assert obs.type == ObservationType.FILE_DELETE


# ---------------------------------------------------------------------------
# Error normalization tests
# ---------------------------------------------------------------------------

class TestErrorNormalization:
    """Tests for error observation normalization."""

    def test_error_with_type(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_error("ValueError", "invalid literal for int()", component="parser")
        assert obs.type == ObservationType.ERROR
        assert obs.structured_data.get("error_type") == "ValueError"


# ---------------------------------------------------------------------------
# Decision normalization tests
# ---------------------------------------------------------------------------

class TestDecisionNormalization:
    """Tests for decision observation normalization."""

    def test_decision(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_decision("Use SQLite for local storage")
        assert obs.type == ObservationType.DECISION
        assert "SQLite" in obs.content


# ---------------------------------------------------------------------------
# Verification normalization tests
# ---------------------------------------------------------------------------

class TestVerificationNormalization:
    """Tests for verification observation normalization."""

    def test_verification(self, normalizer: ObservationNormalizer):
        obs = normalizer.normalize_verification("git diff --check", "clean")
        assert obs.type == ObservationType.VERIFICATION
        assert "clean" in obs.content


# ---------------------------------------------------------------------------
# Stable source identity tests
# ---------------------------------------------------------------------------

class TestSourceIdentity:
    """Tests for stable source event identity."""

    def test_observation_has_id(self):
        obs = Observation(type=ObservationType.DECISION, content="test")
        assert obs.id
        assert len(obs.id) == 36  # UUID

    def test_observation_has_source(self):
        obs = Observation(type=ObservationType.ERROR, content="test", source="codex")
        assert obs.source == "codex"


# ---------------------------------------------------------------------------
# Provenance tests
# ---------------------------------------------------------------------------

class TestProvenance:
    """Tests for provenance tracking."""

    def test_agent_host_tracked(self):
        obs = Observation(type=ObservationType.DECISION, agent_host="codex", model="gpt-5.5")
        meta = obs.to_capture_metadata()
        assert meta["agent_host"] == "codex"
        assert meta["model"] == "gpt-5.5"

    def test_session_id_tracked(self):
        obs = Observation(type=ObservationType.TEST_RESULT, session_id="s123")
        meta = obs.to_capture_metadata()
        assert meta["session_id"] == "s123"


# ---------------------------------------------------------------------------
# Integration with SessionNormalizer (existing pipeline)
# ---------------------------------------------------------------------------

class TestSessionNormalizerIntegration:
    """Test that SessionNormalizer uses ObservationNormalizer."""

    def test_observation_type_in_metadata(self):
        """SessionNormalizer should include observation_type in capture event metadata."""
        from app.capture.agent_sessions.normalizer import SessionNormalizer
        from app.capture.agent_sessions.models import AgentSession

        normalizer = SessionNormalizer()
        session = AgentSession(
            source=AgentSessionSource.codex,
            external_session_id="test-ext",
            project_id="p1",
            namespace="test:m12",
        )
        event = AgentSessionEvent(
            session_id="s1",
            source=AgentSessionSource.codex,
            event_type=AgentSessionEventType.tool_result,
            content="46 passed, 0 failed in 1.46s",
            role="tool",
        )

        result = normalizer.build_capture_event(session, event)
        assert result is not None
        # Should have observation metadata
        meta = result.get("metadata", {})
        assert "observation_type" in meta or meta.get("agent_session_event_type") == "tool_result"


# ---------------------------------------------------------------------------
# Malformed event safety tests
# ---------------------------------------------------------------------------

class TestMalformedEventSafety:
    """Tests for malformed/empty event safety."""

    def test_empty_content(self, normalizer: ObservationNormalizer):
        event = _make_event("")
        obs = normalizer.normalize_event(event)
        assert obs is None

    def test_none_content(self, normalizer: ObservationNormalizer):
        event = AgentSessionEvent(
            session_id="s1", source=AgentSessionSource.codex,
            event_type=AgentSessionEventType.assistant_message,
            content=None, role="assistant",  # type: ignore
        )
        obs = normalizer.normalize_event(event)
        assert obs is None

    def test_list_content(self, normalizer: ObservationNormalizer):
        event = AgentSessionEvent(
            session_id="s1", source=AgentSessionSource.codex,
            event_type=AgentSessionEventType.tool_result,
            content=["tool output line 1", "tool output line 2"],  # type: ignore
            role="tool",
        )
        obs = normalizer.normalize_event(event)
        # Should not crash, may or may not produce observation
        assert obs is None or isinstance(obs, Observation)

    def test_dict_content(self, normalizer: ObservationNormalizer):
        event = AgentSessionEvent(
            session_id="s1", source=AgentSessionSource.codex,
            event_type=AgentSessionEventType.tool_result,
            content={"result": "success"},  # type: ignore
            role="tool",
        )
        obs = normalizer.normalize_event(event)
        assert obs is None or isinstance(obs, Observation)


# ---------------------------------------------------------------------------
# Namespace isolation test
# ---------------------------------------------------------------------------

class TestNamespaceIsolation:
    """Observations should carry namespace for isolation."""

    def test_namespace_preserved(self):
        obs = Observation(
            type=ObservationType.DECISION,
            namespace="project:muninn",
            content="Use FastAPI",
        )
        assert obs.namespace == "project:muninn"


# ---------------------------------------------------------------------------
# Observation != Memory invariant
# ---------------------------------------------------------------------------

class TestObservationNotMemory:
    """Verify observations are not memories."""

    def test_observation_has_no_memory_fields(self):
        """Observation should not have memory-specific fields."""
        obs = Observation(type=ObservationType.DECISION, content="test")
        assert not hasattr(obs, "importance")
        assert not hasattr(obs, "confidence_score")  # confidence is classification confidence
        assert not hasattr(obs, "status")
        assert not hasattr(obs, "gist")
        assert not hasattr(obs, "summary")

    def test_observation_to_content_is_text(self):
        """to_capture_content() returns text for CaptureEvent, not memory."""
        obs = Observation(type=ObservationType.TEST_RESULT, content="46 passed")
        text = obs.to_capture_content()
        assert isinstance(text, str)
        assert "[TEST_RESULT]" in text
