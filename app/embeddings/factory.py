"""Embedding provider factory."""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.sentence_transformer import get_sentence_transformer_provider

logger = logging.getLogger("munin.embeddings")

_provider_override: EmbeddingProvider | None = None


def set_embedding_provider_override(provider: EmbeddingProvider | None) -> None:
    """Override the embedding provider (used by tests). Pass None to clear."""
    global _provider_override
    _provider_override = provider


def get_embedding_provider() -> EmbeddingProvider:
    """
    Resolve the active embedding provider.

    Model loading remains lazy inside the concrete provider.
    If the configured provider (e.g. sentence_transformers) fails to
    initialise, fall back to FakeEmbeddingProvider so the system
    remains functional for memory retrieval using stored embeddings.
    """
    if _provider_override is not None:
        return _provider_override
    return _get_configured_provider()


@lru_cache
def _get_configured_provider() -> EmbeddingProvider:
    cfg = get_settings()
    provider = cfg.embedding_provider.strip().lower()

    if provider in {"sentence_transformers", "sentence-transformers"}:
        return _SafeSentenceTransformerFallback(
            model_name=cfg.embedding_model,
            device=cfg.embedding_device,
            local_files_only=cfg.embedding_local_files_only,
        )

    raise EmbeddingError(f"Unsupported embedding provider: {cfg.embedding_provider}")


class _SafeSentenceTransformerFallback(EmbeddingProvider):
    """Wraps sentence-transformers with automatic fallback to FakeEmbeddingProvider.

    The real provider is lazy-loaded; if it fails (e.g. package not installed,
    model weights missing) we transparently fall back so the system can still
    retrieve memories that were embedded with the fake provider.
    """

    def __init__(self, *, model_name: str, device: str, local_files_only: bool) -> None:
        self._model_name = model_name
        self._device = device
        self._local_files_only = local_files_only
        self._real: EmbeddingProvider | None = None
        self._fallback: EmbeddingProvider | None = None
        self._resolved = False

    def _resolve(self) -> EmbeddingProvider:
        if not self._resolved:
            self._resolved = True
            try:
                # Quick check: can we even import the package?
                import sentence_transformers as _st  # noqa: F401
                real = get_sentence_transformer_provider(
                    model_name=self._model_name,
                    device=self._device,
                    local_files_only=self._local_files_only,
                )
                self._real = real
                logger.info(
                    "Using sentence_transformers provider model=%s",
                    self._model_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sentence-transformers unavailable (%s), "
                    "falling back to FakeEmbeddingProvider",
                    exc,
                )
                from app.embeddings.fake import FakeEmbeddingProvider
                self._fallback = FakeEmbeddingProvider()
        if self._real is not None:
            return self._real
        assert self._fallback is not None
        return self._fallback

    @property
    def provider_name(self) -> str:
        return self._resolve().provider_name

    @property
    def model_name(self) -> str:
        return self._resolve().model_name

    @property
    def dimension(self) -> int:
        return self._resolve().dimension

    def embed_text(self, text: str) -> list[float]:
        return self._resolve().embed_text(text)

    def embed_batch(self, texts: list[list[str]]) -> list[list[float]]:
        return self._resolve().embed_batch(texts)
