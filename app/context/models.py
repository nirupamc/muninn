"""Context assembly internal models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.memory import Memory, MemoryType


class SkipReason(str, Enum):
    """Why a candidate was not selected for context."""

    REDUNDANT = "REDUNDANT"
    OUT_OF_BUDGET = "OUT_OF_BUDGET"
    SUPERSEDED = "SUPERSEDED"
    NOT_VALID_AT_AS_OF = "NOT_VALID_AT_AS_OF"
    FILTERED = "FILTERED"
    MAX_MEMORIES = "MAX_MEMORIES"


class ReasonCode(str, Enum):
    """Explainability codes for selected memories."""

    HIGH_SEMANTIC_RELEVANCE = "HIGH_SEMANTIC_RELEVANCE"
    HIGH_IMPORTANCE = "HIGH_IMPORTANCE"
    RECENT = "RECENT"
    REINFORCED = "REINFORCED"
    TYPE_RELEVANT = "TYPE_RELEVANT"
    CONFLICT_PARTIAL = "CONFLICT_PARTIAL"


@dataclass
class ScoredCandidate:
    """One ranked memory candidate with component scores."""

    memory: Memory
    semantic_score: float
    importance: float
    confidence: float
    recency_score: float
    type_relevance: float
    reinforcement_score: float
    final_score: float
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class SelectedMemory:
    """A memory selected for assembled context."""

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
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class ConflictPair:
    """Two active memories in unresolved contradiction."""

    memory_id_a: str
    content_a: str
    memory_id_b: str
    content_b: str


@dataclass
class AssemblyTrace:
    """Internal trace of assembly decisions."""

    candidate_count: int
    selected_count: int
    skipped: dict[str, list[str]] = field(default_factory=dict)
    conflict_pairs: list[ConflictPair] = field(default_factory=list)


@dataclass
class ContextConfig:
    """Runtime configuration for context assembly."""

    max_candidates: int = 50
    max_memories: int = 20
    token_budget: int = 1500
    max_token_budget: int = 20000
    redundancy_threshold: float = 0.85
    weight_semantic: float = 0.45
    weight_importance: float = 0.20
    weight_confidence: float = 0.10
    weight_recency: float = 0.10
    weight_type_relevance: float = 0.10
    weight_reinforcement: float = 0.05
    recency_lambda: float = 0.05
    min_semantic_score: float = 0.0
    # M6 decay integration
    decay_enabled: bool = True
