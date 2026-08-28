"""M12 — Observation types and domain model.

Defines the canonical observation types and the Observation dataclass
used internally by the normalization pipeline.

Observation != Memory. Observations flow through existing admission.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class ObservationType(str, enum.Enum):
    """Canonical observation types for structured agent/tool activity."""

    # Messages
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"

    # Decisions
    DECISION = "decision"

    # Tool activity
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Commands
    COMMAND_RUN = "command_run"
    COMMAND_RESULT = "command_result"

    # File changes
    FILE_EDIT = "file_edit"
    FILE_CREATE = "file_create"
    FILE_DELETE = "file_delete"

    # Tests
    TEST_RUN = "test_run"
    TEST_RESULT = "test_result"

    # Git
    GIT_COMMIT = "git_commit"

    # Build
    BUILD_RESULT = "build_result"

    # API
    API_RESULT = "api_result"

    # Verification
    VERIFICATION = "verification"

    # Errors / warnings
    ERROR = "error"
    WARNING = "warning"
    BLOCKER = "blocker"

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Fallback
    OTHER = "other"


# Observation types that are high-value memory candidates
HIGH_VALUE_TYPES = frozenset({
    ObservationType.DECISION,
    ObservationType.TEST_RESULT,
    ObservationType.ERROR,
    ObservationType.BLOCKER,
    ObservationType.VERIFICATION,
    ObservationType.BUILD_RESULT,
    ObservationType.GIT_COMMIT,
})

# Observation types that are typically low-value / noise
NOISE_TYPES = frozenset({
    ObservationType.USER_MESSAGE,
    ObservationType.AGENT_MESSAGE,
    ObservationType.TOOL_CALL,
    ObservationType.TOOL_RESULT,
    ObservationType.COMMAND_RUN,
    ObservationType.SESSION_START,
    ObservationType.SESSION_END,
    ObservationType.OTHER,
})


@dataclass
class Observation:
    """A canonical structured observation of something that happened.

    This is an internal domain model — NOT an ORM entity.
    It maps to a CaptureEvent for persistence via the existing pipeline.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: ObservationType = ObservationType.OTHER

    # Project / namespace
    project_id: str | None = None
    namespace: str | None = None

    # Agent provenance
    agent_host: str | None = None  # e.g., "codex", "cline"
    model: str | None = None  # e.g., "gpt-5.5", "mimo-2.5"
    session_id: str | None = None

    # Actor / action / target
    actor: str | None = None  # who/what did it
    action: str | None = None  # what was done
    target: str | None = None  # what was acted upon

    # Content
    content: str = ""  # human-readable description
    structured_data: dict[str, Any] = field(default_factory=dict)

    # Provenance
    source: str = "unknown"  # adapter source name
    source_event_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Quality
    confidence: float = 1.0  # 0-1, how confident we are in the classification

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_capture_content(self) -> str:
        """Generate human-readable content for CaptureEvent persistence."""
        parts = []

        # Add type label
        parts.append(f"[{self.type.value.upper()}]")

        # Add actor/action/target if available
        if self.actor:
            parts.append(f"Actor: {self.actor}")
        if self.action:
            parts.append(f"Action: {self.action}")
        if self.target:
            parts.append(f"Target: {self.target}")

        # Add main content
        if self.content:
            parts.append(self.content)

        # Add key structured data summaries
        if self.structured_data:
            for key in ("command", "passed", "failed", "exit_code", "path", "error_type"):
                if key in self.structured_data:
                    parts.append(f"{key}: {self.structured_data[key]}")

        return "\n".join(parts)

    def to_capture_metadata(self) -> dict[str, Any]:
        """Generate metadata dict for CaptureEvent persistence."""
        meta: dict[str, Any] = {
            "observation_type": self.type.value,
            "observation_id": self.id,
        }
        if self.agent_host:
            meta["agent_host"] = self.agent_host
        if self.model:
            meta["model"] = self.model
        if self.session_id:
            meta["session_id"] = self.session_id
        if self.actor:
            meta["actor"] = self.actor
        if self.action:
            meta["action"] = self.action
        if self.target:
            meta["target"] = self.target
        if self.structured_data:
            meta["structured_data"] = self.structured_data
        if self.confidence < 1.0:
            meta["classification_confidence"] = self.confidence
        meta.update(self.metadata)
        return meta
