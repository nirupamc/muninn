"""Token estimator abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TokenEstimator(ABC):
    """Estimate token counts for text without model-specific tokenizers."""

    @abstractmethod
    def count(self, text: str) -> int:
        """Return estimated token count for the given text."""
