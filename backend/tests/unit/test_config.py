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
    """Unlike its sibling tests in this file, this one asserts the *default* rather than
    an explicit env override, so it must isolate itself from any ambient `.env` -- a local
    `backend/.env` that sets `FINTRADE_IBKR_BASE_URL` (e.g. left over from IBKR-gateway
    research, as this dev container's own `.env` does) would otherwise make `Settings()`
    silently pick that up via `Settings.model_config`'s `env_file=".env"` (relative to
    CWD) and fail this assertion despite the code itself being correct. `_env_file=None`
    bypasses that `.env` lookup entirely for this one construction (pydantic-settings
    supports overriding `model_config` fields per-instance via a leading-underscore kwarg;
    mypy doesn't know about that dynamic signature, hence the narrow ignore)."""
    assert Settings(_env_file=None).ibkr_base_url == "https://localhost:5000/v1/api"  # type: ignore[call-arg]


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
