"""Structured temporal relationship models for M4."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TemporalRelationshipType(str, Enum):
    """How a NEW candidate relates temporally to an existing active memory."""

    NEW = "NEW"
    UPDATES = "UPDATES"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"


class TemporalReasonCode(str, Enum):
    """Machine-readable temporal reason codes."""

    EXPLICIT_REPLACEMENT = "EXPLICIT_REPLACEMENT"
    NO_LONGER = "NO_LONGER"
    NOW_PREFERENCE = "NOW_PREFERENCE"
    NEGATED_PREFERENCE = "NEGATED_PREFERENCE"
    DETAIL_UPDATE = "DETAIL_UPDATE"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    RELATED_BUT_NEW = "RELATED_BUT_NEW"
    NO_SIMILAR_CANDIDATES = "NO_SIMILAR_CANDIDATES"
    RELATIONSHIP_UNCERTAIN = "RELATIONSHIP_UNCERTAIN"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class TemporalRelationshipAnalysis(BaseModel):
    """Validated provider output for one candidate ↔ memory pair."""

    relationship: TemporalRelationshipType
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str | None = None
    replacement_scope: str | None = None
