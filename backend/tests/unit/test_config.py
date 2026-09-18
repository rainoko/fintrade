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
