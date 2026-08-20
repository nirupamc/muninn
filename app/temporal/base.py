"""Temporal relationship provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.models.memory import MemoryType
from app.temporal.models import TemporalRelationshipAnalysis


class TemporalRelationshipError(Exception):
    """Raised when temporal classification fails or the provider is unavailable."""


class TemporalRelationshipProvider(ABC):
    """Classify temporal/update relationships between a candidate and an existing memory."""

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
        candidate_event_time: datetime | None = None,
        existing_valid_from: datetime | None = None,
        existing_valid_until: datetime | None = None,
    ) -> TemporalRelationshipAnalysis:
        """Return structured temporal analysis. Never returns free-form prose alone."""
