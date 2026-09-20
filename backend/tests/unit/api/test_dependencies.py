"""Unit tests for app/api/dependencies.py's `get_data_provider` and `get_ibkr_provider`
composition.

Only checks the object graph each dependency wires together (real network calls would
violate docs/architecture/Testing.md's "no live network calls in any test" rule and
aren't exercised here — no provider method is ever called).
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import (
    _get_ibkr_provider_singleton,
    get_data_provider,
    get_ibkr_provider,
)
from app.config import get_settings
from app.data.cache import CachedDataProvider
from app.data.fixture_provider import FixtureDataProvider
from app.data.ibkr_provider import IBKRProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.models import Base


@pytest.fixture(autouse=True)
def _reset_ibkr_provider_singleton() -> Iterator[None]:
    """`_get_ibkr_provider_singleton` (app/api/dependencies.py) is an
    `lru_cache(maxsize=1)`-wrapped module-level singleton -- a plain `monkeypatch`
    can't revert a call that actually populates its cache (that's a mutation the
    `lru_cache` object itself makes, not one `monkeypatch` performed), so without
    this an `IBKRProvider` constructed by one test (bound to that test's
    monkeypatched `base_url`/mock transport) could otherwise leak into a later test
    in the same pytest session -- including one that reaches `get_ibkr_provider`
    indirectly through a real route via FastAPI's `TestClient` rather than calling
    it directly. Runs before *and* after every test in this module so a test that
    forgets to enable IBKR still starts from an empty cache. Found during PR #190's
    re-review (docs/tasks/backend-ibkr-data-provider-followups.json).
    """
    _get_ibkr_provider_singleton.cache_clear()
    yield
    _get_ibkr_provider_singleton.cache_clear()


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

    def test_enabled_yields_a_configured_provider_and_leaves_it_open_on_cleanup(self, monkeypatch) -> None:
        """Unlike `get_data_provider`, the yielded `IBKRProvider` is a process-wide
        singleton that outlives the request -- it must NOT be closed once the generator
        is driven past its `yield` (there's no `finally: provider.close()` here), since
        closing it every request would discard the in-memory scanner-params cache and
        `run_scanner` throttle state that's the whole point of reusing one instance."""
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        monkeypatch.setenv("FINTRADE_IBKR_BASE_URL", "https://localhost:5001/v1/api")
        get_settings.cache_clear()

        try:
            generator = get_ibkr_provider()
            provider = next(generator)

            assert isinstance(provider, IBKRProvider)
            assert provider._base_url == "https://localhost:5001/v1/api"

            # The generator still ends (FastAPI still drives it past the yield at the
            # end of a request), just with nothing to clean up.
            with pytest.raises(StopIteration):
                next(generator)
        finally:
            get_settings.cache_clear()

    def test_enabled_reuses_the_same_singleton_across_calls(self, monkeypatch) -> None:
        """Two separate dependency resolutions (i.e. two separate requests) must reuse
        the same `IBKRProvider` instance, not construct a fresh one each time -- this is
        what actually makes the scanner-params cache and run_scanner throttle protect
        anything across requests."""
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        get_settings.cache_clear()

        try:
            first = next(get_ibkr_provider())
            second = next(get_ibkr_provider())

            assert first is second
        finally:
            get_settings.cache_clear()
