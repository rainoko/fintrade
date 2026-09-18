from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_prefix="FINTRADE_", env_file=".env")

    database_url: str = "sqlite:///./fintrade.db"

    # "live" (default): app.api.dependencies.get_data_provider wires the real
    # yfinance-primary/Stooq-fallback provider behind the SQLite cache, same as
    # every environment before this setting existed. "fixture": it returns
    # app.data.fixture_provider.FixtureDataProvider instead -- a deterministic,
    # no-network synthetic data source used only by the frontend e2e test suite
    # (frontend/tests/e2e/, run via `npm run test:e2e`) so that suite never
    # depends on live market data or produces flaky signal output from real
    # market noise. Never set in the live app's own default config or in the
    # pytest suite (which mocks providers directly instead -- see
    # docs/architecture/Testing.md); see docs/tasks/frontend-e2e-tests.json's
    # `decisions` entry for the full rationale.
    data_provider_mode: Literal["live", "fixture"] = "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()
