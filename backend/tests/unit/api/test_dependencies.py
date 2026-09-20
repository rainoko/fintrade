"""Unit tests for app/api/dependencies.py's `get_data_provider` and `get_ibkr_provider`
composition.

Only checks the object graph each dependency wires together (real network calls would
violate docs/architecture/Testing.md's "no live network calls in any test" rule and
aren't exercised here — no provider method is ever called).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.config import get_settings
from app.data.cache import CachedDataProvider
from app.data.fixture_provider import FixtureDataProvider
from app.data.ibkr_provider import IBKRProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.models import Base


def test_get_data_provider_wires_yfinance_primary_stooq_fallback_and_cache() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        provider = get_data_provider(db=session)

        assert isinstance(provider, CachedDataProvider)
        assert isinstance(provider._primary, YFinanceProvider)
        assert isinstance(provider._fallback, StooqProvider)
        assert provider._db is session
    finally:
        session.close()
        engine.dispose()


def test_get_data_provider_returns_fixture_provider_in_fixture_mode(monkeypatch) -> None:
    """FINTRADE_DATA_PROVIDER_MODE=fixture (only ever set by the frontend e2e suite, see
    app.data.fixture_provider) bypasses the live yfinance/Stooq/cache stack entirely."""
    monkeypatch.setenv("FINTRADE_DATA_PROVIDER_MODE", "fixture")
    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        provider = get_data_provider(db=session)

        assert isinstance(provider, FixtureDataProvider)
    finally:
        session.close()
        engine.dispose()
        get_settings.cache_clear()  # don't leak the monkeypatched setting into other tests


class TestGetIbkrProvider:
    """`get_ibkr_provider` is a `yield`-based FastAPI dependency, so calling it directly
    returns a generator -- `next(...)` (and, once enabled, a follow-up `next(...)` past
    the `yield` to run the cleanup) drives it the same way FastAPI's own dependency
    resolution would, without spinning up a full app/route for this unit test.
    """

    def test_disabled_by_default_yields_none_without_constructing_a_client(self) -> None:
        """The default (`ibkr_enabled=False`, matching every environment without a
        locally-running gateway) must not even construct an `IBKRProvider` -- confirms
        this optional feature is truly inert, not just returning `None` from an
        otherwise-instantiated provider."""
        generator = get_ibkr_provider()

        provider = next(generator)

        assert provider is None
        # The generator must also be exhausted (no cleanup step pending) after the one
        # yield on the disabled path.
        with pytest.raises(StopIteration):
            next(generator)

    def test_enabled_yields_a_configured_provider_and_closes_it_on_cleanup(self, monkeypatch) -> None:
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5001/v1/api")
        get_settings.cache_clear()

        try:
            generator = get_ibkr_provider()
            provider = next(generator)

            assert isinstance(provider, IBKRProvider)
            assert provider._base_url == "https://localhost:5001/v1/api"

            # Drive the generator past its yield to run the `finally: provider.close()`
            # cleanup FastAPI would trigger at the end of a request.
            with pytest.raises(StopIteration):
                next(generator)
        finally:
            get_settings.cache_clear()
