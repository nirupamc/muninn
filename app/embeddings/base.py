"""Embedding provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingError(Exception):
    """Raised when embedding generation or model loading fails."""


class EmbeddingProvider(ABC):
    """Provider-independent interface for text embeddings."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier stored with embeddings."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier stored with embeddings."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimensionality for the active model."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Embed a single text. Prefer L2-normalized vectors."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Prefer L2-normalized vectors."""
