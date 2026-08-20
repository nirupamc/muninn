"""Embedding provider factory."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.sentence_transformer import get_sentence_transformer_provider

_provider_override: EmbeddingProvider | None = None


def set_embedding_provider_override(provider: EmbeddingProvider | None) -> None:
    """Override the embedding provider (used by tests). Pass None to clear."""
    global _provider_override
    _provider_override = provider


def get_embedding_provider() -> EmbeddingProvider:
    """
    Resolve the active embedding provider.

    Model loading remains lazy inside the concrete provider.
    """
    if _provider_override is not None:
        return _provider_override
    return _get_configured_provider()


@lru_cache
def _get_configured_provider() -> EmbeddingProvider:
    cfg = get_settings()
    provider = cfg.embedding_provider.strip().lower()

    if provider in {"sentence_transformers", "sentence-transformers"}:
        return get_sentence_transformer_provider(
            model_name=cfg.embedding_model,
            device=cfg.embedding_device,
        )

    raise EmbeddingError(f"Unsupported embedding provider: {cfg.embedding_provider}")
