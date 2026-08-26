"""Agent session domain models for M8.3."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class AgentSessionSource(str, enum.Enum):
    """Source of the agent session."""

    codex = "codex"
    kilo = "kilo"
    opencode = "opencode"
    generic = "generic"


class AgentSessionStatus(str, enum.Enum):
    """Status of an agent session."""

    active = "active"
    finished = "finished"
    stale = "stale"
    error = "error"


class AgentSessionEventType(str, enum.Enum):
    """Type of agent session event."""

    session_started = "session_started"
    session_finished = "session_finished"
    user_message = "user_message"
    assistant_message = "assistant_message"
    tool_call = "tool_call"
    tool_result = "tool_result"
    decision = "decision"
    bug = "bug"
    fix = "fix"
    milestone = "milestone"
    blocker = "blocker"
    constraint = "constraint"
    summary = "summary"


@dataclass
class AgentSession:
    """Represents a coding agent session."""

    source: AgentSessionSource
    external_session_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str | None = None
    project_id: str | None = None
    namespace: str | None = None
    project_path: str | None = None
    title: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: AgentSessionStatus = AgentSessionStatus.active
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.status == AgentSessionStatus.finished

    @property
    def is_active(self) -> bool:
        return self.status == AgentSessionStatus.active

    @property
    def is_stale(self) -> bool:
        return self.status == AgentSessionStatus.stale


@dataclass
class AgentSessionEvent:
    """Represents an event within an agent session."""

    session_id: str
    source: AgentSessionSource
    event_type: AgentSessionEventType
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    external_event_id: str | None = None
    role: str | None = None  # user, assistant, system, tool
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    fingerprint: str | None = None

    @property
    def is_user_message(self) -> bool:
        return self.role == "user"

    @property
    def is_assistant_message(self) -> bool:
        return self.role == "assistant"

    @property
    def is_tool_call(self) -> bool:
        return self.event_type == AgentSessionEventType.tool_call

    @property
    def is_tool_result(self) -> bool:
        return self.event_type == AgentSessionEventType.tool_result
