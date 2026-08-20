"""Memory request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.memory import MemoryStatus, MemoryType


class MemoryCreate(BaseModel):
    """Payload for creating a memory."""

    namespace: str = Field(default="default", min_length=1)
    user_id: str | None = None
    agent_id: str | None = None
    content: str
    memory_type: MemoryType
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: MemoryStatus = MemoryStatus.active
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

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

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> MemoryCreate:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must be greater than or equal to valid_from")
        return self


class MemoryUpdate(BaseModel):
    """Partial update payload for a memory."""

    content: str | None = None
    memory_type: MemoryType | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MemoryStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.strip()):
            raise ValueError("content must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> MemoryUpdate:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must be greater than or equal to valid_from")
        return self


class MemoryRead(BaseModel):
    """Memory returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    user_id: str | None
    agent_id: str | None
    content: str
    memory_type: MemoryType
    importance: float
    confidence: float
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    source_event_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")


class MemorySearchRequest(BaseModel):
    """Semantic search request."""

    query: str
    namespace: str = Field(..., min_length=1)
    user_id: str | None = None
    agent_id: str | None = None
    memory_types: list[MemoryType] | None = None
    statuses: list[MemoryStatus] | None = None
    limit: int = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

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


class MemorySearchResult(BaseModel):
    """One ranked semantic search hit."""

    memory: MemoryRead
    score: float


class MemorySearchResponse(BaseModel):
    """Semantic search response envelope."""

    query: str
    namespace: str
    count: int
    results: list[MemorySearchResult]
