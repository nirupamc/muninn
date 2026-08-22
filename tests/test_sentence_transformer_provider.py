"""Focused regression tests for local-first sentence-transformer loading."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.embeddings.base import EmbeddingError
from app.embeddings.sentence_transformer import SentenceTransformerProvider


class _Model:
    def encode(self, texts, **kwargs):  # noqa: ANN001, ANN201
        assert kwargs["normalize_embeddings"] is True
        return np.ones((len(texts), 384), dtype=np.float32) / np.sqrt(384)


def test_cached_model_loads_local_only_and_preserves_dimension(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def constructor(model_name: str, **kwargs):  # noqa: ANN202
        calls.append({"model_name": model_name, **kwargs})
        return _Model()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=constructor),
    )
    provider = SentenceTransformerProvider("test/model", device="cpu")

    assert provider.dimension == 384
    assert calls == [
        {"model_name": "test/model", "device": "cpu", "local_files_only": True}
    ]
    assert len(provider.embed_text("hello")) == 384


def test_cache_miss_allows_first_time_download(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def constructor(model_name: str, **kwargs):  # noqa: ANN202
        calls.append({"model_name": model_name, **kwargs})
        if kwargs.get("local_files_only"):
            raise OSError("not cached")
        return _Model()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=constructor),
    )

    assert SentenceTransformerProvider("test/model").dimension == 384
    assert calls[0]["local_files_only"] is True
    assert "local_files_only" not in calls[1]


def test_forced_local_mode_fails_clearly_without_fallback(monkeypatch) -> None:
    calls = 0

    def constructor(model_name: str, **kwargs):  # noqa: ANN202, ARG001
        nonlocal calls
        calls += 1
        raise OSError("not cached")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=constructor),
    )
    provider = SentenceTransformerProvider("missing/model", local_files_only=True)

    with pytest.raises(EmbeddingError, match="not available locally"):
        _ = provider.dimension
    assert calls == 1
