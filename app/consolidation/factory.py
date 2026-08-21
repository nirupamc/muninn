"""Consolidation provider factory."""

from __future__ import annotations

from app.consolidation.base import ConsolidationProvider

_override: ConsolidationProvider | None = None


def set_consolidation_provider_override(provider: ConsolidationProvider | None) -> None:
    global _override
    _override = provider


def get_consolidation_provider() -> ConsolidationProvider:
    if _override is not None:
        return _override

    from app.config import get_settings
    settings = get_settings()

    if settings.consolidation_provider == "openai_compatible":
        from app.consolidation.providers.openai_compatible import OpenAICompatibleConsolidationProvider
        return OpenAICompatibleConsolidationProvider(
            base_url=settings.consolidation_base_url,
            model=settings.consolidation_model,
            api_key=settings.consolidation_api_key,
        )

    from app.consolidation.providers.deterministic import DeterministicConsolidationProvider
    return DeterministicConsolidationProvider()
