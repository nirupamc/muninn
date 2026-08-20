"""Deterministic embedding provider for tests."""

from __future__ import annotations

import hashlib
import re

import numpy as np

from app.embeddings.base import EmbeddingProvider
from app.embeddings.vector_utils import l2_normalize


class FakeEmbeddingProvider(EmbeddingProvider):
    """
    Predictable embeddings driven by keyword topic axes.

    Used so ranking/search tests remain deterministic without downloading models.
    """

    def __init__(
        self,
        *,
        model_name: str = "fake-mini",
        dimension: int = 8,
        provider_name: str = "fake",
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._provider_name = provider_name
        # Topic axes — similar keywords land near each other.
        self._topic_terms: dict[str, int] = {
            "pdf": 0,
            "document": 0,
            "documents": 0,
            "parser": 0,
            "parsing": 0,
            "ragparser": 0,
            "memory": 1,
            "memories": 1,
            "munin": 1,
            "agent": 1,
            "agents": 1,
            "llm": 2,
            "language": 2,
            "model": 2,
            "models": 2,
            # Extra axes for M3 preference / stack tests (keeps dim=8).
            "python": 3,
            "backend": 3,
            "prefer": 3,
            "prefers": 3,
            "preferred": 3,
            "fastapi": 4,
            "sqlite": 4,
            "postgresql": 4,
            "openai": 5,
            "apis": 5,
            "local": 6,
            "rust": 7,
            "javascript": 7,
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        vec = np.zeros(self._dimension, dtype=np.float32)

        matched = False
        for term, axis in self._topic_terms.items():
            if term in tokens and axis < self._dimension:
                vec[axis] += 1.0
                matched = True

        # Cluster preference / usage statements so temporal shortlist works in tests.
        if tokens & {"prefer", "prefers", "preferred", "preference"}:
            vec[3] += 3.0
            matched = True
        if tokens & {"use", "uses", "using", "used"}:
            vec[4] += 3.0
            matched = True

        # Stable residual so different unrelated texts are not identical.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        for i in range(self._dimension):
            vec[i] += (digest[i] / 255.0) * (0.03 if matched else 0.5)

        return l2_normalize(vec).astype(float).tolist()
