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


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
