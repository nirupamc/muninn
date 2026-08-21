"""Context assembly request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.models.memory import MemoryType


class ContextRequest(BaseModel):
    """Payload for assembling agent context from durable memory."""

    query: str
    namespace: str

    user_id: str | None = None
    agent_id: str | None = None

    token_budget: int = Field(default=1500, gt=0)
    max_candidates: int = Field(default=50, ge=1, le=200)
    max_memories: int = Field(default=20, ge=1, le=100)

    memory_types: list[MemoryType] | None = None
    include_superseded: bool = False

    as_of: datetime | None = None

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

    @field_validator("token_budget")
    @classmethod
    def token_budget_within_max(cls, value: int) -> int:
        settings = get_settings()
        if value > settings.context_max_token_budget:
            raise ValueError(
                f"token_budget must not exceed {settings.context_max_token_budget}"
            )
        return value

    @field_validator("max_candidates")
    @classmethod
    def max_candidates_within_config(cls, value: int) -> int:
        settings = get_settings()
        if value > settings.context_max_candidates:
            raise ValueError(
                f"max_candidates must not exceed {settings.context_max_candidates}"
            )
        return value

    @field_validator("max_memories")
    @classmethod
    def max_memories_within_config(cls, value: int) -> int:
        settings = get_settings()
        if value > settings.context_default_max_memories:
            raise ValueError(
                f"max_memories must not exceed {settings.context_default_max_memories}"
            )
        return value


class MemoryUsed(BaseModel):
    """One memory included in assembled context with explainability trace."""

    memory_id: str
    memory_type: MemoryType
    content: str
    semantic_score: float
    importance: float
    confidence: float
    recency_score: float
    type_relevance: float
    reinforcement_score: float
    final_score: float
    estimated_tokens: int
    reason_codes: list[str] = Field(default_factory=list)


class ContextResponse(BaseModel):
    """Assembled context for an agent task."""

    query: str
    namespace: str
    context: str
    token_budget: int
    estimated_tokens: int
    truncated: bool
    memories_used: list[MemoryUsed]
