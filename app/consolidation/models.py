"""Consolidation internal models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.memory import MemoryType


@dataclass
class ConsolidationProposal:
    """
    Structured output from a consolidation provider.

    source_memory_ids are supplied by the caller (validated, not invented by the LLM).
    """

    content: str
    memory_type: MemoryType
    importance: float
    confidence: float
    source_memory_ids: list[str]
    reason: str
    provider: str
    provider_model: str


class ConsolidateRequest(BaseModel):
    """Request to consolidate a group of memories."""

    namespace: str
    user_id: str | None = None
    memory_ids: list[str] = Field(min_length=1)
    # If True, validate + run provider but persist nothing
    dry_run: bool = False


class ConsolidatePreviewRequest(BaseModel):
    """Request for a preview (no persistence)."""

    namespace: str
    user_id: str | None = None
    memory_ids: list[str] = Field(min_length=1)


class SourceMemoryRead(BaseModel):
    """Lightweight source memory summary for provenance responses."""

    memory_id: str
    content: str
    memory_type: MemoryType


class ConsolidationRead(BaseModel):
    """Consolidation audit record returned via API."""

    consolidation_id: str
    created_memory_id: str
    namespace: str
    user_id: str | None
    provider: str
    provider_model: str
    confidence: float
    reason: str
    created_at: datetime
    sources: list[SourceMemoryRead] = Field(default_factory=list)


class ConsolidateResponse(BaseModel):
    """Response from a successful consolidation."""

    consolidated_memory_id: str
    namespace: str
    content: str
    memory_type: MemoryType
    importance: float
    confidence: float
    source_memory_ids: list[str]
    reason: str
    is_new: bool  # False if equivalent consolidation already existed


class ConsolidatePreviewResponse(BaseModel):
    """Preview of what would be created — nothing persisted."""

    namespace: str
    proposed_content: str
    proposed_memory_type: MemoryType
    proposed_importance: float
    proposed_confidence: float
    source_memory_ids: list[str]
    reason: str
    would_be_duplicate: bool
