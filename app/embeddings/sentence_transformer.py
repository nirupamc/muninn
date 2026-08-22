"""Local sentence-transformers embedding provider."""

from __future__ import annotations

import logging
from functools import lru_cache

from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.vector_utils import l2_normalize

logger = logging.getLogger("munin.embeddings")


class SentenceTransformerProvider(EmbeddingProvider):
    """Lazy-loaded sentence-transformers provider (CPU by default)."""

    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        *,
        local_files_only: bool = False,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._local_files_only = local_files_only
        self._model = None
        self._dimension: int | None = None

    @property
    def provider_name(self) -> str:
        return "sentence_transformers"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        self._ensure_model()
        assert self._dimension is not None
        return self._dimension

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed; "
                "install project dependencies to enable local embeddings"
            ) from exc

        try:
            logger.info(
                "Loading embedding model provider=%s model=%s device=%s",
                self.provider_name,
                self._model_name,
                self._device,
            )
            try:
                # Prefer the local Hugging Face cache. Without this flag the
                # library probes the Hub for optional metadata even when model
                # weights are already present.
                self._model = SentenceTransformer(
                    self._model_name,
                    device=self._device,
                    local_files_only=True,
                )
            except Exception as local_exc:  # noqa: BLE001
                if self._local_files_only:
                    raise EmbeddingError(
                        "Embedding model is not available locally: "
                        f"{self._model_name}. Download it during initial setup "
                        "or disable EMBEDDING_LOCAL_FILES_ONLY."
                    ) from local_exc
                logger.info(
                    "Embedding model not found in local cache; allowing initial download "
                    "model=%s",
                    self._model_name,
                )
                self._model = SentenceTransformer(
                    self._model_name,
                    device=self._device,
                )
            # Probe dimension without logging content.
            probe = self._model.encode(
                ["dimension-probe"],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            self._dimension = int(probe.shape[1])
            logger.info(
                "Embedding model ready provider=%s model=%s dimension=%s",
                self.provider_name,
                self._model_name,
                self._dimension,
            )
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as EmbeddingError
            logger.error(
                "Embedding model could not be loaded provider=%s model=%s",
                self.provider_name,
                self._model_name,
            )
            raise EmbeddingError(
                f"Embedding model could not be loaded: {self._model_name}"
            ) from exc

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_model()
        assert self._model is not None
        try:
            vectors = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError("Failed to generate embeddings") from exc

        result: list[list[float]] = []
        for row in vectors:
            normalized = l2_normalize(row)
            result.append(normalized.astype(float).tolist())
        return result


@lru_cache
def get_sentence_transformer_provider(
    model_name: str,
    device: str,
    local_files_only: bool = False,
) -> SentenceTransformerProvider:
    """Return a process-cached provider instance for the given configuration."""
    return SentenceTransformerProvider(
        model_name=model_name,
        device=device,
        local_files_only=local_files_only,
    )
