"""Temporal relationship provider factory."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.temporal.base import TemporalRelationshipError, TemporalRelationshipProvider
from app.temporal.providers.deterministic import DeterministicTemporalProvider
from app.temporal.providers.openai_compatible import OpenAICompatibleTemporalProvider

_provider_override: TemporalRelationshipProvider | None = None


def set_temporal_provider_override(provider: TemporalRelationshipProvider | None) -> None:
    """Override temporal provider (tests). Pass None to clear."""
    global _provider_override
    _provider_override = provider


def get_temporal_provider() -> TemporalRelationshipProvider:
    if _provider_override is not None:
        return _provider_override
    return _get_configured_provider()


@lru_cache
def _get_configured_provider() -> TemporalRelationshipProvider:
    cfg = get_settings()
    name = cfg.temporal_provider.strip().lower()

    if name in {"deterministic", "rules"}:
        return DeterministicTemporalProvider()

    if name in {"openai_compatible", "openai-compatible", "openai"}:
        return OpenAICompatibleTemporalProvider(
            base_url=cfg.temporal_base_url,
            model=cfg.temporal_model,
            api_key=cfg.temporal_api_key or None,
        )

    raise TemporalRelationshipError(
        f"Unsupported temporal provider: {cfg.temporal_provider}"
    )
