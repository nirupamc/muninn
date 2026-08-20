"""Admission provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.admission.models import AdmissionAnalysis


class AdmissionError(Exception):
    """Raised when admission analysis fails or the provider is unavailable."""


class AdmissionProvider(ABC):
    """Extract structured memory candidates from an event."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier persisted on audit rows."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model / rule-set identifier persisted on audit rows."""

    @abstractmethod
    def analyze_event(
        self,
        *,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> AdmissionAnalysis:
        """Return structured candidate analyses. Never returns free-form prose alone."""
