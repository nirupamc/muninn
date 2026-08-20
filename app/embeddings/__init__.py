"""Embedding providers and vector utilities."""

from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.factory import get_embedding_provider

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "get_embedding_provider",
]
