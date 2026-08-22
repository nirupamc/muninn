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
        explicit_remember: bool = False,
    ) -> AdmissionAnalysis:
        """Return structured candidate analyses. Never returns free-form prose alone.

        ``explicit_remember`` signals that the caller explicitly requested
        persistence (e.g., via a high-level ``remember()`` API), as opposed to
        an ordinary conversational event. Providers may boost explicitness and
        future utility for such calls, but privacy/triviality filters still apply.
        """
