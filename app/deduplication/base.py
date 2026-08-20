"""Relationship provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.deduplication.models import RelationshipAnalysis
from app.models.memory import MemoryType


class RelationshipError(Exception):
    """Raised when relationship classification fails or the provider is unavailable."""


class RelationshipProvider(ABC):
    """Classify how a candidate relates to an existing memory."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier persisted on audit rows."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model / rule-set identifier persisted on audit rows."""

    @abstractmethod
    def classify(
        self,
        *,
        candidate: str,
        existing_memory: str,
        candidate_type: MemoryType,
        existing_type: MemoryType,
    ) -> RelationshipAnalysis:
        """Return structured relationship analysis. Never returns free-form prose alone."""
