"""M13 — Memory debugger data contract schemas.

Defines the read-only response models for the memory debug API.
All fields are safe for read-only exposure; no write operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DebugMemoryIdentity(BaseModel):
    """Memory identity panel data."""

    memory_id: str
    project_id: str | None = None
    namespace: str
    memory_type: str
    status: str
    importance: float
    confidence: float
    created_at: datetime
    updated_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class DebugRepresentations(BaseModel):
    """L0/L1/L2 representation data."""

    l0_gist: str | None = None
    l1_summary: str | None = None
    l2_content: str
    l0_token_cost: int = 0
    l1_token_cost: int = 0
    l2_token_cost: int = 0
    available_levels: list[str] = Field(default_factory=list)


class DebugProvenance(BaseModel):
    """Source / provenance panel data."""

    agent_host: str | None = None
    model: str | None = None
    session_id: str | None = None
    observation_type: str | None = None
    observation_id: str | None = None
    capture_event_id: str | None = None
    source: str | None = None
    source_event_id: str | None = None
    timestamp: datetime | None = None


class DebugAdmission(BaseModel):
    """Why stored — admission decision trace."""

    decision: str
    admission_score: float
    importance: float | None = None
    confidence: float | None = None
    future_utility: float | None = None
    stability: float | None = None
    specificity: float | None = None
    explicitness: float | None = None
    triviality: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    provider: str | None = None
    model_name: str | None = None
    created_at: datetime | None = None


class DebugDedup(BaseModel):
    """Dedup / reinforcement trace."""

    relationship: str
    matched_memory_id: str | None = None
    relationship_confidence: float | None = None
    similarity_score: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    created_new_memory: bool = False


class DebugReinforcement(BaseModel):
    """Reinforcement provenance record."""

    source_event_id: str
    candidate_content: str
    relationship_confidence: float
    created_at: datetime


class DebugTemporal(BaseModel):
    """Temporal relationship trace."""

    relationship: str
    matched_memory_id: str | None = None
    created_memory_id: str | None = None
    relationship_confidence: float | None = None
    similarity_score: float | None = None
    old_status: str | None = None
    new_old_status: str | None = None
    old_valid_until_before: datetime | None = None
    old_valid_until_after: datetime | None = None
    new_valid_from: datetime | None = None
    reason_codes: list[str] = Field(default_factory=list)


class DebugMemoryView(BaseModel):
    """Complete debug view for one memory.

    Groups all traceable information into logical sections.
    Missing sections return null/empty gracefully — no 500 for
    historical memories lacking newer trace data.
    """

    # Identity
    identity: DebugMemoryIdentity

    # Representations
    representations: DebugRepresentations

    # Provenance
    provenance: DebugProvenance

    # Why stored
    admission: DebugAdmission | None = None

    # Dedup / reinforcement
    dedup: DebugDedup | None = None
    reinforcements: list[DebugReinforcement] = Field(default_factory=list)
    reinforcement_count: int = 0

    # Temporal
    temporal: list[DebugTemporal] = Field(default_factory=list)

    # Source observations (capture events)
    source_events: list[DebugSourceEvent] = Field(default_factory=list)


class DebugSourceEvent(BaseModel):
    """One source capture event for a memory."""

    capture_event_id: str
    source: str
    event_type: str
    agent_id: str | None = None
    session_id: str | None = None
    observation_type: str | None = None
    observation_id: str | None = None
    content_preview: str
    admission_decision: str | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebugObservationView(BaseModel):
    """Debug view for one capture event / observation."""

    capture_event_id: str
    source: str
    event_type: str
    namespace: str
    agent_id: str | None = None
    session_id: str | None = None
    observation_type: str | None = None
    observation_id: str | None = None
    content_preview: str
    admission_decision: str | None = None
    memory_id: str | None = None
    occurred_at: datetime | None = None
    captured_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebugTimelineEntry(BaseModel):
    """One entry in the recent debug timeline."""

    timestamp: datetime
    event_type: str  # OBSERVED, FILTERED, ADMITTED, STORED, IGNORED, etc.
    source: str
    namespace: str | None = None
    memory_id: str | None = None
    content_preview: str
    details: dict[str, Any] = Field(default_factory=dict)
