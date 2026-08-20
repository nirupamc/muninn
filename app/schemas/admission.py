"""API/response schemas for memory admission."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.event import EventRole
from app.models.memory import MemoryType


class AdmitEventResultItem(BaseModel):
    """One admission result for an event."""

    decision: str
    memory_id: str | None = None
    memory_type: MemoryType | str | None = None
    content: str | None = None
    admission_score: float
    importance: float | None = None
    confidence: float | None = None
    future_utility: float | None = None
    stability: float | None = None
    specificity: float | None = None
    explicitness: float | None = None
    triviality: float | None = None
    reason_codes: list[str] = Field(default_factory=list)


class AdmitEventResponse(BaseModel):
    """Response for POST /events/{id}/admit."""

    event_id: str
    processed: int
    stored: int
    ignored: int
    results: list[AdmitEventResultItem]
    idempotent_replay: bool = False


class AdmissionRecordRead(BaseModel):
    """Persisted admission audit row (safe for API)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    candidate_content: str | None
    memory_type: str | None
    decision: str
    admission_score: float
    importance: float | None
    confidence: float | None
    future_utility: float | None
    stability: float | None
    specificity: float | None
    explicitness: float | None
    triviality: float | None
    reason_codes: list[str]
    created_memory_id: str | None
    provider: str
    model_name: str
    created_at: datetime


class AnalyzeAdmissionRequest(BaseModel):
    """Debug endpoint: analyze without persisting."""

    role: EventRole = EventRole.user
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return value


class AnalyzeAdmissionCandidate(BaseModel):
    decision: str
    content: str | None
    memory_type: MemoryType | str | None = None
    admission_score: float
    importance: float | None = None
    confidence: float | None = None
    future_utility: float | None = None
    stability: float | None = None
    specificity: float | None = None
    explicitness: float | None = None
    triviality: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str | None = None


class AnalyzeAdmissionResponse(BaseModel):
    processed: int
    would_store: int
    would_ignore: int
    results: list[AnalyzeAdmissionCandidate]
    provider: str
    model_name: str
