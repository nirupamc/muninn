"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for Munin."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    munin_env: str = "development"
    database_url: str = "sqlite:///./data/munin.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    admission_provider: str = "deterministic"
    admission_store_threshold: float = 0.65
    admission_min_confidence: float = 0.60
    admission_base_url: str = ""
    admission_model: str = ""
    admission_api_key: str = ""

    # M3 — Deduplication & Reinforcement
    dedup_provider: str = "deterministic"
    dedup_candidate_limit: int = 5
    dedup_min_similarity: float = 0.55
    dedup_relationship_min_confidence: float = 0.70
    dedup_base_url: str = ""
    dedup_model: str = ""
    dedup_api_key: str = ""

    # M4 — Contradiction + Temporal Memory
    temporal_provider: str = "deterministic"
    temporal_candidate_limit: int = 5
    temporal_min_similarity: float = 0.50
    temporal_relationship_min_confidence: float = 0.75
    temporal_base_url: str = ""
    temporal_model: str = ""
    temporal_api_key: str = ""

    # M6 — Decay
    decay_enabled: bool = True
    decay_lambda_none: float = 0.0
    decay_lambda_slow: float = 0.002
    decay_lambda_normal: float = 0.01
    decay_lambda_fast: float = 0.05
    decay_lambda_ephemeral: float = 0.20

    # M6 — Consolidation
    consolidation_provider: str = "deterministic"
    consolidation_min_group_size: int = 3
    consolidation_max_group_size: int = 10
    consolidation_min_similarity: float = 0.60
    consolidation_min_confidence: float = 0.75
    consolidation_base_url: str = ""
    consolidation_model: str = ""
    consolidation_api_key: str = ""

    # M5 — Context Assembly
    context_max_candidates: int = 50
    context_default_max_memories: int = 20
    context_weight_semantic: float = 0.45
    context_weight_importance: float = 0.20
    context_weight_confidence: float = 0.10
    context_weight_recency: float = 0.10
    context_weight_type_relevance: float = 0.10
    context_weight_reinforcement: float = 0.05
    context_redundancy_threshold: float = 0.85
    context_default_token_budget: int = 1500
    context_max_token_budget: int = 20000
    context_recency_lambda: float = 0.05


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
