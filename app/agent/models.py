"""Agent-facing request/response models (M7A).

These schemas are intentionally small and high-level. They hide the
internal M2 admission / M3 dedup / M4 temporal / embedding pipeline
so an external agent only deals with ``remember`` and ``get context``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.event import EventRole
from app.models.memory import MemoryType
from app.schemas.context import MemoryUsed


class AgentRememberRequest(BaseModel):
    """High-level "remember this interaction" payload."""

    namespace: str = Field(..., min_length=1)
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    role: EventRole = EventRole.assistant
    content: str
    # Optional client-supplied key so transport retries never create duplicates.
    idempotency_key: str | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return value

    @field_validator("namespace")
    @classmethod
    def namespace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("namespace must not be empty or whitespace-only")
        return value.strip()


class AgentRememberResponse(BaseModel):
    """Compact outcome of a remember call (audit internals hidden)."""

    event_id: str
    remembered: bool
    decision: str = "STORE"  # STORE or IGNORE
    memory_id: str | None = None
    dedup_relationship: str | None = None
    temporal_relationship: str | None = None
    idempotent_replay: bool = False


class AgentContextRequest(BaseModel):
    """Agent-friendly context retrieval payload."""

    query: str
    namespace: str = Field(..., min_length=1)
    user_id: str | None = None
    agent_id: str | None = None
    token_budget: int = Field(default=1500, gt=0)
    max_memories: int = Field(default=20, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("query must not be empty or whitespace-only")
        return value

    @field_validator("namespace")
    @classmethod
    def namespace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("namespace must not be empty or whitespace-only")
        return value.strip()


class AgentContextResponse(BaseModel):
    """Assembled, agent-ready context.

    ``text`` is the assembled durable memory as **data**, not a privileged
    system instruction. Integrations should present it as untrusted context.
    """

    query: str
    namespace: str
    text: str
    estimated_tokens: int
    truncated: bool
    memories_used: list[MemoryUsed] = Field(default_factory=list)
    as_of: datetime | None = None