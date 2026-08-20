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


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
