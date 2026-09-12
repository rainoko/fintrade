from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_prefix="FINTRADE_", env_file=".env")

    database_url: str = "sqlite:///./fintrade.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
