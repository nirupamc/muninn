"""Relationship provider factory."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.deduplication.base import RelationshipError, RelationshipProvider
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.deduplication.providers.openai_compatible import OpenAICompatibleRelationshipProvider

_provider_override: RelationshipProvider | None = None


def set_relationship_provider_override(provider: RelationshipProvider | None) -> None:
    """Override relationship provider (tests). Pass None to clear."""
    global _provider_override
    _provider_override = provider


def get_relationship_provider() -> RelationshipProvider:
    if _provider_override is not None:
        return _provider_override
    return _get_configured_provider()


@lru_cache
def _get_configured_provider() -> RelationshipProvider:
    cfg = get_settings()
    name = cfg.dedup_provider.strip().lower()

    if name in {"deterministic", "rules"}:
        return DeterministicRelationshipProvider()

    if name in {"openai_compatible", "openai-compatible", "openai"}:
        return OpenAICompatibleRelationshipProvider(
            base_url=cfg.dedup_base_url,
            model=cfg.dedup_model,
            api_key=cfg.dedup_api_key or None,
        )

    raise RelationshipError(f"Unsupported deduplication provider: {cfg.dedup_provider}")
