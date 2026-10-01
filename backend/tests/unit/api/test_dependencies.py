"""Unit tests for app/api/dependencies.py's `get_data_provider` and `get_ibkr_provider`
composition.

Only checks the object graph each dependency wires together (real network calls would
violate docs/architecture/Testing.md's "no live network calls in any test" rule and
aren't exercised here — no provider method is ever called).
"""

import concurrent.futures
import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import (
    _get_ibkr_provider_singleton,
    _reset_ibkr_provider_singleton_for_tests,
    get_data_provider,
    get_data_provider_factory,
    get_ibkr_provider,
)
from app.config import get_settings
from app.data.cache import CachedDataProvider
from app.data.exceptions import DataProviderUnavailableError
from app.data.fixture_provider import FixtureDataProvider
from app.data.ibkr_data_provider import IBKRDataProvider, IBKRPrimaryDataProvider
from app.data.ibkr_provider import GatewayStatus, IBKRProvider, IBKRUnavailableError
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.models import Base


@pytest.fixture(autouse=True)
def _reset_ibkr_provider_singleton() -> Iterator[None]:
    """`_ibkr_provider_singleton` (app/api/dependencies.py) is a module-level global
    mutated by application code via a `global` assignment inside a lock -- a plain
    `monkeypatch` can't reliably revert that (it's not a mutation monkeypatch itself
    made), so without this an `IBKRProvider` constructed by one test (bound to that
    test's monkeypatched `base_url`/mock transport) could otherwise leak into a later
    test in the same pytest session -- including one that reaches `get_ibkr_provider`
    indirectly through a real route via FastAPI's `TestClient` rather than calling it
    directly. Runs before *and* after every test in this module so a test that forgets
    to enable IBKR still starts from an unset singleton. Found during PR #190's
    re-review (docs/tasks/backend-ibkr-data-provider-followups.json).
    """
    _reset_ibkr_provider_singleton_for_tests()
    yield
    _reset_ibkr_provider_singleton_for_tests()


def test_get_data_provider_wires_yfinance_primary_stooq_fallback_and_cache(monkeypatch) -> None:
    """Forces `FINTRADE_IBKR_ENABLED=false` explicitly (rather than relying on
    `Settings.ibkr_enabled`'s own default) for the same reason
    `TestGetIbkrProvider.test_disabled_by_default_yields_none_without_constructing_a_client`
    already does: this dev container's own real `backend/.env` can have
    `FINTRADE_IBKR_ENABLED=true` set for manual live-gateway checking
    (`backend-ibkr-primary-data-provider`'s own standing constraints), and
    `get_data_provider` now calls `_is_ibkr_connected()` -- without this override, this
    test would make a real network call against whatever `FINTRADE_IBKR_BASE_URL` the
    ambient `.env` configures, violating docs/architecture/Testing.md's "no live network
    calls in any test" rule."""
    monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
    get_settings.cache_clear()

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
        get_settings.cache_clear()


class TestGetDataProviderIBKRPrimary:
    """`get_data_provider`/`_build_live_data_provider` switching to IBKR as the primary
    source while its gateway is connected (`backend-ibkr-primary-data-provider`) --
    mocks `IBKRProvider.get_gateway_status` at the same boundary
    `tests/unit/data/test_ibkr_provider.py` itself uses, per docs/architecture/Testing.md.
    """

    def _session(self):  # type: ignore[no-untyped-def]
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)(), engine

    def test_ibkr_available_returns_ibkr_primary_provider(self, monkeypatch, mocker) -> None:
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        get_settings.cache_clear()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=GatewayStatus(state="available"),
        )
        session, engine = self._session()

        try:
            provider = get_data_provider(db=session)

            assert isinstance(provider, IBKRPrimaryDataProvider)
            ohlcv = provider._ohlcv_provider
            assert isinstance(ohlcv, CachedDataProvider)
            assert isinstance(ohlcv._primary, IBKRDataProvider)
            # Primary and fallback are the SAME instance -- see
            # `_build_ibkr_primary_data_provider`'s own docstring for why this is
            # deliberate: no yfinance/Stooq fallback on a per-call IBKR failure while
            # connected.
            assert ohlcv._fallback is ohlcv._primary
            extended = provider._extended_data_provider
            assert isinstance(extended, CachedDataProvider)
            assert isinstance(extended._primary, YFinanceProvider)
            assert isinstance(extended._fallback, StooqProvider)
        finally:
            session.close()
            engine.dispose()
            get_settings.cache_clear()

    def test_ibkr_not_authenticated_falls_back_to_yfinance_stooq(self, monkeypatch, mocker) -> None:
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        get_settings.cache_clear()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=GatewayStatus(state="not_authenticated", detail="please log in"),
        )
        session, engine = self._session()

        try:
            provider = get_data_provider(db=session)

            assert isinstance(provider, CachedDataProvider)
            assert isinstance(provider._primary, YFinanceProvider)
            assert isinstance(provider._fallback, StooqProvider)
        finally:
            session.close()
            engine.dispose()
            get_settings.cache_clear()

    def test_ibkr_disabled_falls_back_to_yfinance_stooq_without_checking_gateway(
        self, monkeypatch, mocker
    ) -> None:
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
        get_settings.cache_clear()
        status_check = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=GatewayStatus(state="available"),
        )
        session, engine = self._session()

        try:
            provider = get_data_provider(db=session)

            assert isinstance(provider, CachedDataProvider)
            assert isinstance(provider._primary, YFinanceProvider)
            status_check.assert_not_called()
        finally:
            session.close()
            engine.dispose()
            get_settings.cache_clear()

    def test_ohlcv_never_calls_yfinance_or_stooq_while_ibkr_connected_even_on_ibkr_failure(
        self, monkeypatch, mocker
    ) -> None:
        """Regression test for this task's own explicit, no-exceptions requirement: a
        per-call IBKR OHLCV failure must never fall back to yfinance/Stooq while IBKR is
        connected (unlike the non-IBKR path's own primary/fallback behavior) -- it must
        surface as `DataProviderUnavailableError` instead. Patches `YFinanceProvider`'s
        and `StooqProvider`'s own OHLCV methods to fail the test immediately if ever
        called, covering both the happy path and an IBKR-side failure.
        """
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        get_settings.cache_clear()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=GatewayStatus(state="available"),
        )

        def _fail_if_called(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("yfinance/Stooq OHLCV must never be called while IBKR is connected")

        mocker.patch.object(YFinanceProvider, "get_daily_ohlcv", side_effect=_fail_if_called)
        mocker.patch.object(YFinanceProvider, "get_weekly_ohlcv", side_effect=_fail_if_called)
        mocker.patch.object(StooqProvider, "get_daily_ohlcv", side_effect=_fail_if_called)
        mocker.patch.object(StooqProvider, "get_weekly_ohlcv", side_effect=_fail_if_called)

        session, engine = self._session()
        try:
            provider = get_data_provider(db=session)

            # Happy path: IBKR itself serves the data.
            payload = {
                "data": [{"t": 1665149400000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100.0}]
            }
            search_payload = [{"conid": "265598", "symbol": "AAPL", "sections": [{"secType": "STK"}]}]
            mocker.patch(
                "app.data.ibkr_provider.IBKRProvider._request",
                side_effect=lambda method, path, **kw: search_payload
                if path == "/iserver/secdef/search"
                else payload,
            )
            result = provider.get_daily_ohlcv("AAPL")
            assert len(result) == 1

            # IBKR itself failing must raise, not silently fall back to yfinance/Stooq.
            mocker.patch(
                "app.data.ibkr_provider.IBKRProvider._request",
                side_effect=IBKRUnavailableError("boom"),
            )
            with pytest.raises(DataProviderUnavailableError):
                provider.get_daily_ohlcv("MSFT")
        finally:
            session.close()
            engine.dispose()
            get_settings.cache_clear()


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


class TestGetDataProviderFactory:
    """`get_data_provider_factory` (app/api/dependencies.py) -- the per-call-scoped
    `DataProvider` factory `GET /api/stocks/{ticker}/analysis` (`app.api.routers.stocks
    .get_analysis`) uses instead of `get_data_provider`'s single shared instance, so an
    abandoned concurrent leg's own `Session` lifecycle can never race the request's own
    `get_db` teardown -- see that function's own docstring and docs/tasks/
    backend-data-provider-timeouts.json's `decisions` entry (PR #360's second review round)."""

    def test_live_mode_yields_a_fresh_cached_provider_with_its_own_session_each_call(
        self, monkeypatch
    ) -> None:
        # See test_get_data_provider_wires_yfinance_primary_stooq_fallback_and_cache's own
        # docstring for why this explicit override is needed despite this test never
        # mentioning IBKR itself -- `_build_live_data_provider` (shared by both
        # `get_data_provider` and this factory) now checks `Settings.ibkr_enabled`.
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
        get_settings.cache_clear()
        try:
            factory = get_data_provider_factory()

            with factory() as first_provider:
                assert isinstance(first_provider, CachedDataProvider)
                assert isinstance(first_provider._primary, YFinanceProvider)
                assert isinstance(first_provider._fallback, StooqProvider)
                first_session = first_provider._db

            with factory() as second_provider:
                # A genuinely distinct `DataProvider`/`Session` each call -- not the same
                # instance reused, which would reintroduce exactly the shared-session race
                # this factory exists to avoid between two concurrently-running calls.
                assert second_provider is not first_provider
                assert second_provider._db is not first_session
        finally:
            get_settings.cache_clear()

    def test_live_mode_closes_its_own_session_on_scope_exit(self, monkeypatch) -> None:
        """The whole point of this factory over `get_data_provider`'s shared instance: each
        scope's `Session` is closed by that same scope, on whatever thread runs it, independent
        of the request's own `db` -- not left for something else (or nothing at all) to close
        later. Verified by tracking real `sqlalchemy.orm.Session.close()` calls rather than by
        probing post-close behavior directly: SQLAlchemy's `Session` deliberately tolerates
        further use after `close()` (it silently opens a fresh transaction), so an attempted
        query after close proves nothing either way about whether `close()` was actually called.
        """
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
        get_settings.cache_clear()
        close_calls: list[SQLAlchemySession] = []
        original_close = SQLAlchemySession.close

        def _tracking_close(self: SQLAlchemySession) -> None:
            close_calls.append(self)
            original_close(self)

        monkeypatch.setattr(SQLAlchemySession, "close", _tracking_close)

        factory = get_data_provider_factory()
        try:
            with factory() as provider:
                opened_session = provider._db
                assert close_calls == []  # not yet closed while still inside the `with` block

            assert close_calls == [opened_session]
        finally:
            get_settings.cache_clear()

    def test_fixture_mode_returns_the_same_fixture_provider_every_call(self, monkeypatch) -> None:
        """Fixture mode (only ever set by the frontend e2e suite) has no real `Session` to
        protect at all -- see `get_data_provider`'s own docstring -- so the factory can safely
        keep handing back the same stateless instance instead of constructing a fresh one."""
        monkeypatch.setenv("FINTRADE_DATA_PROVIDER_MODE", "fixture")
        get_settings.cache_clear()

        try:
            factory = get_data_provider_factory()

            with factory() as first_provider, factory() as second_provider:
                assert isinstance(first_provider, FixtureDataProvider)
                assert first_provider is second_provider
        finally:
            get_settings.cache_clear()


class TestGetIbkrProvider:
    """`get_ibkr_provider` is a `yield`-based FastAPI dependency, so calling it directly
    returns a generator -- `next(...)` (and, once enabled, a follow-up `next(...)` past
    the `yield` to run the cleanup) drives it the same way FastAPI's own dependency
    resolution would, without spinning up a full app/route for this unit test.
    """

    def test_disabled_by_default_yields_none_without_constructing_a_client(
        self, monkeypatch
    ) -> None:
        """The default (`ibkr_enabled=False`, matching every environment without a
        locally-running gateway) must not even construct an `IBKRProvider` -- confirms
        this optional feature is truly inert, not just returning `None` from an
        otherwise-instantiated provider. Unlike this class's other tests, this one
        asserts the *default* rather than an explicit env override, so it must isolate
        itself from any ambient `.env` (e.g. a local `backend/.env` with
        `FINTRADE_IBKR_ENABLED=true`, plausible leftover dev-machine state per
        app/config.py's own `ibkr_enabled` docstring) -- unlike test_config.py's own
        analogous fix, `get_ibkr_provider` reads `Settings` via the process-wide cached
        `get_settings()`, not a `Settings` this test constructs directly, so there's no
        call site here to pass `_env_file=None` into. `monkeypatch.setenv` instead
        (env vars take priority over `.env` file values in pydantic-settings' precedence
        order, same mechanism this class's other tests already rely on to *enable* IBKR
        despite that same ambient `.env` never setting it) forces the default explicitly,
        with `get_settings.cache_clear()` on both sides so neither the monkeypatched env
        nor a stale cached `Settings` leaks into another test."""
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
        get_settings.cache_clear()

        try:
            generator = get_ibkr_provider()

            provider = next(generator)

            assert provider is None
            # The generator must also be exhausted (no cleanup step pending) after the
            # one yield on the disabled path.
            with pytest.raises(StopIteration):
                next(generator)
        finally:
            get_settings.cache_clear()

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

    def test_concurrent_first_requests_construct_only_one_singleton(self, monkeypatch) -> None:
        """Regression test for PR #191's review finding: a purely sequential call
        (`test_enabled_reuses_the_same_singleton_across_calls` above) can't catch a
        race that only manifests when multiple threads observe a cold singleton at
        the same time -- it would pass under the pre-fix `lru_cache`-only
        implementation just as easily as it passes now. This spawns many threads that
        all race `_get_ibkr_provider_singleton()` simultaneously against a definitely
        cold singleton (the autouse fixture above already resets it, but the reset is
        asserted here too for clarity) and asserts every thread got back the exact
        same object -- not just equal, `is`-identical -- which only holds if the
        double-checked locking in app/api/dependencies.py actually serializes
        construction rather than letting every racing thread build its own instance.
        """
        monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "true")
        get_settings.cache_clear()

        try:
            _reset_ibkr_provider_singleton_for_tests()

            thread_count = 32
            barrier = threading.Barrier(thread_count)

            def race_the_singleton() -> IBKRProvider:
                # Every thread waits here so they all call the getter as close to
                # simultaneously as possible, maximizing the odds of hitting the
                # cold-cache race window if the locking regresses.
                barrier.wait()
                return _get_ibkr_provider_singleton()

            with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = [executor.submit(race_the_singleton) for _ in range(thread_count)]
                instances = [future.result() for future in futures]

            assert len(instances) == thread_count
            first_instance = instances[0]
            assert all(instance is first_instance for instance in instances)
        finally:
            get_settings.cache_clear()
