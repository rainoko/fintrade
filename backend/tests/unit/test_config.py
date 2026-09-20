"""Tests for app/config.py's Settings, focused on `data_provider_mode` (the switch the
frontend e2e suite uses to select app.data.fixture_provider.FixtureDataProvider — see
app.api.dependencies.get_data_provider). `database_url` is already covered indirectly by
tests/unit/test_db_session.py.
"""

from app.config import Settings, get_settings


def test_data_provider_mode_defaults_to_live() -> None:
    """The live app (and every existing deployment/test that predates this setting) must
    keep getting the real yfinance/Stooq-backed provider without opting in to anything."""
    assert Settings().data_provider_mode == "live"


def test_data_provider_mode_reads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("FINTRADE_DATA_PROVIDER_MODE", "fixture")
    get_settings.cache_clear()

    try:
        assert get_settings().data_provider_mode == "fixture"
    finally:
        get_settings.cache_clear()


def test_ibkr_enabled_defaults_to_false() -> None:
    """Every existing environment (dev, CI, this task's own sandboxed implementation
    session) has no locally-running gateway -- the optional IBKR provider must stay off
    unless explicitly opted into (app.data.ibkr_provider.IBKRProvider)."""
    assert Settings().ibkr_enabled is False


def test_ibkr_base_url_defaults_to_localhost_gateway() -> None:
    assert Settings().ibkr_base_url == "https://localhost:5000/v1/api"


def test_ibkr_enabled_reads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
    get_settings.cache_clear()

    try:
        assert get_settings().ibkr_enabled is True
    finally:
        get_settings.cache_clear()


def test_ibkr_base_url_reads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5001/v1/api")
    get_settings.cache_clear()

    try:
        assert get_settings().ibkr_base_url == "https://localhost:5001/v1/api"
    finally:
        get_settings.cache_clear()
