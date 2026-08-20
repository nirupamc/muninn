"""Structured relationship analysis models for M3."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RelationshipType(str, Enum):
    """How a STORE candidate relates to an existing memory."""

    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REINFORCES = "REINFORCES"


class DedupReasonCode(str, Enum):
    """Machine-readable deduplication reason codes."""

    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NORMALIZED_DUPLICATE = "NORMALIZED_DUPLICATE"
    SEMANTIC_DUPLICATE = "SEMANTIC_DUPLICATE"
    REINFORCEMENT = "REINFORCEMENT"
    RELATED_BUT_NEW = "RELATED_BUT_NEW"
    NO_SIMILAR_CANDIDATES = "NO_SIMILAR_CANDIDATES"
    RELATIONSHIP_UNCERTAIN = "RELATIONSHIP_UNCERTAIN"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TYPE_MISMATCH_PRESERVE = "TYPE_MISMATCH_PRESERVE"


class RelationshipAnalysis(BaseModel):
    """Validated provider output for one candidate ↔ memory pair."""

    relationship: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str | None = None
