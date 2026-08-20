"""Admission provider factory."""

from __future__ import annotations

from functools import lru_cache

from app.admission.base import AdmissionError, AdmissionProvider
from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.admission.providers.openai_compatible import OpenAICompatibleAdmissionProvider
from app.config import get_settings

_provider_override: AdmissionProvider | None = None


def set_admission_provider_override(provider: AdmissionProvider | None) -> None:
    """Override admission provider (tests). Pass None to clear."""
    global _provider_override
    _provider_override = provider


def get_admission_provider() -> AdmissionProvider:
    if _provider_override is not None:
        return _provider_override
    return _get_configured_provider()


@lru_cache
def _get_configured_provider() -> AdmissionProvider:
    cfg = get_settings()
    name = cfg.admission_provider.strip().lower()

    if name in {"deterministic", "rules"}:
        return DeterministicAdmissionProvider()

    if name in {"openai_compatible", "openai-compatible", "openai"}:
        return OpenAICompatibleAdmissionProvider(
            base_url=cfg.admission_base_url,
            model=cfg.admission_model,
            api_key=cfg.admission_api_key or None,
        )

    raise AdmissionError(f"Unsupported admission provider: {cfg.admission_provider}")
