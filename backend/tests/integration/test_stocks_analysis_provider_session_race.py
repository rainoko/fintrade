"""Regression test for PR #360's second review round: `GET /api/stocks/{ticker}/analysis`'s
concurrent daily/weekly/extended-data fetch (`app.api.routers.stocks.get_analysis`) could leave
an abandoned leg (e.g. a slow `get_extended_data` still running after a fast-failing daily fetch
already made the response return) writing through `CachedDataProvider` (app/data/cache.py) on
the exact same `Session` the request's own `Depends(get_db)` was about to close, via `get_db`'s
`finally: db.close()` (app/db/session.py). A live `Session` touched from two threads at once with
no coordination between them reproduced `sqlalchemy.exc.IllegalStateChangeError` on roughly
30-40% of runs during that review round.

Fixed by giving each concurrent leg its own independently-scoped `Session`
(`app.api.dependencies.get_data_provider_factory`) instead of sharing the request's own `db` --
see that function's own docstring and docs/tasks/backend-data-provider-timeouts.json's
`decisions` entry.

Deliberately exercises the REAL `get_data_provider_factory` -> `CachedDataProvider` ->
`SessionLocal`/`Session` machinery end to end, unlike tests/integration/test_stocks_analysis.py
(which overrides `get_data_provider_factory` itself with a plain stub that has no `Session` of
its own to race -- that override bypasses this exact race entirely, which is why PR #360's first
review round's test suite didn't catch it). Only the outermost data source
(`YFinanceProvider`/`StooqProvider`) is replaced, by monkeypatching the classes
`app.api.dependencies.get_data_provider_factory` constructs -- no live network call is ever made
(docs/architecture/Testing.md) -- while `CachedDataProvider`, `get_data_provider_factory`, and
`get_db` all run unmodified, on a real (in-memory, `StaticPool`-backed so it's shared across the
worker threads `TestClient`/`ThreadPoolExecutor` actually use) SQLite engine.

`_racing_providers` also forces `FINTRADE_IBKR_ENABLED=false`
(`backend-ibkr-primary-data-provider`'s PR #369 review follow-up fix): `_live_scope` -> `_build_
live_data_provider` now calls `_is_ibkr_connected()` before ever reaching
`YFinanceProvider`/`StooqProvider`, which would otherwise make a REAL `GET /iserver/auth/status`
call against whatever `FINTRADE_IBKR_BASE_URL` this dev container's own ambient `backend/.env`
configures (`FINTRADE_IBKR_ENABLED=true`, per that task's own standing constraints) --
independently confirmed via socket-connect tracing before this fix (3 real outbound TCP connect()
attempts per run of this one file) -- the same concern/fix as
`tests/unit/api/test_dependencies.py`'s and `tests/integration/test_portfolio_get_db_wiring.py`'s
own `FINTRADE_IBKR_ENABLED=false` overrides. Without this, a live-authenticated gateway at test
time would also silently route this test's real `_live_scope` call through the real
`IBKRProvider`/`IBKRDataProvider` instead of `_RacingPrimaryProvider`/`_UnusedFallbackProvider`,
defeating this regression test's own purpose.

Run as a real regression test (not a one-off manual repro): `TestRepeatedFastFailWithSlowAbandonedLeg`
below runs many iterations of the exact fast-fail/slow-other-leg scenario, since this is a race
condition -- a single passing run proves nothing about whether the race is still reachable,
only that it didn't happen to trigger this particular time.
"""

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

import app.api.dependencies as dependencies_module
import app.db.session as db_session_module
from app.config import get_settings
from app.data.base import DataProvider, ExtendedData
from app.data.exceptions import TickerNotFoundError
from app.db.models import Base, ExtendedDataCacheORM
from app.main import app

_TICKER = "AAPL"


class _RacingPrimaryProvider(DataProvider):
    """A real (non-cached) `DataProvider` stand-in used as the *primary* provider
    `get_data_provider_factory` wraps in a real `CachedDataProvider` -- unlike
    tests/integration/test_stocks_analysis.py's `_StubProvider` (which stands in for the whole
    `DataProvider` `get_analysis` receives, bypassing `CachedDataProvider`/`Session` entirely).

    `get_daily_ohlcv` raises `TickerNotFoundError` immediately (no sleep), so the request fails
    fast; `get_weekly_ohlcv` returns almost instantly; `get_extended_data` sleeps `sleep_seconds`
    before returning, forcing its own `CachedDataProvider._upsert_extended` commit into the
    window after the daily leg has already made the response return -- the exact
    abandoned-leg-still-writing scenario PR #360's second review round reproduced.
    """

    def __init__(self, *, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise TickerNotFoundError(f"ticker {ticker!r} not found")

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        index = pd.date_range("2020-01-03", periods=30, freq="W-FRI")
        return pd.DataFrame(
            {
                "open": [1.0] * len(index),
                "high": [1.0] * len(index),
                "low": [1.0] * len(index),
                "close": [1.0] * len(index),
                "volume": [1.0] * len(index),
            },
            index=index,
        )

    def get_extended_data(self, ticker: str) -> ExtendedData:
        time.sleep(self._sleep_seconds)
        return ExtendedData(
            earnings_date=None,
            ex_dividend_date=None,
            shares_short=None,
            short_ratio=None,
            short_percent_of_float=None,
            float_shares=None,
            insider_transactions=[],
        )


class _UnusedFallbackProvider(DataProvider):
    """The fallback provider `get_data_provider_factory` wraps alongside
    `_RacingPrimaryProvider` -- never actually reached, since none of `_RacingPrimaryProvider`'s
    methods raise `DataProviderUnavailableError` (the only exception `CachedDataProvider` treats
    as fallback-worthy; `TickerNotFoundError` propagates directly -- see app/data/cache.py's own
    docstrings). Raises `AssertionError` if ever actually called, so a future change to
    `_RacingPrimaryProvider` that accidentally triggers a fallback fails loudly here instead of
    silently reaching a real network call."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise AssertionError("fallback provider should never be reached in this test")

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise AssertionError("fallback provider should never be reached in this test")

    def get_extended_data(self, ticker: str) -> ExtendedData:
        raise AssertionError("fallback provider should never be reached in this test")


@pytest.fixture
def _shared_engine_session_factories(tmp_path, monkeypatch):
    """A single shared on-disk SQLite engine -- a real temp file, *not* `:memory:` +
    `StaticPool` (deliberately -- see below) -- so every thread (the request thread `TestClient`
    runs on, and this endpoint's own daily/weekly/extended-data worker threads, each opening its
    own `Session`/connection concurrently) sees the same schema/data. Wired into both
    `app.api.dependencies.SessionLocal` (what `get_data_provider_factory`'s per-leg sessions
    actually use) and `app.db.session.SessionLocal` (what `get_db` itself uses for this request's
    own `db`).

    Patched on the two *importing* modules' own namespaces, not just `app.db.session`'s
    original definition: `app.api.dependencies` did `from app.db.session import SessionLocal,
    get_db`, which copies the name into its own module namespace at import time -- monkeypatching
    only `app.db.session.SessionLocal` would leave `app.api.dependencies`'s already-imported copy
    untouched, and `get_data_provider_factory`'s `_live_scope` closure looks up `SessionLocal` in
    `app.api.dependencies`'s own module globals, not `app.db.session`'s.

    A real file (mirroring `app/db/session.py`'s own real, non-`:memory:` `engine` -- same
    `connect_args`, default pool class, not `StaticPool`) rather than an in-memory `StaticPool`
    engine: `StaticPool` forces every `Session` opened against it -- daily's, weekly's,
    extended's, all three genuinely concurrent now that each has its own independently-scoped
    session -- onto the literal same underlying DBAPI connection object. Two sessions issuing
    statements concurrently against one shared physical `sqlite3` connection from different
    threads is its own, different hazard (interleaved cursor/statement state on one connection)
    that doesn't reflect production at all (production's real on-disk engine hands each `Session`
    its own separate pooled connection) -- confirmed by hitting exactly that artifact (a garbled
    row read back as `None`) when this fixture used `:memory:` + `StaticPool` during this test's
    own development. A real file lets each concurrently-opened `Session` get its own genuinely
    separate connection, same as production, so this test's own DB plumbing doesn't introduce a
    race that isn't the one actually being tested.
    """
    db_path = tmp_path / "test_stocks_analysis_provider_session_race.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    monkeypatch.setattr(dependencies_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(db_session_module, "SessionLocal", test_session_local)

    try:
        yield engine, test_session_local
    finally:
        engine.dispose()


@pytest.fixture
def _racing_providers(monkeypatch):
    """Monkeypatches the two data-source classes `get_data_provider_factory`'s `_live_scope`
    constructs (`app.api.dependencies.YFinanceProvider`/`.StooqProvider`) so every `CachedDataProvider`
    it builds wraps `_RacingPrimaryProvider`/`_UnusedFallbackProvider` instead -- no live network
    call is ever reachable through this path (docs/architecture/Testing.md).

    Also forces `FINTRADE_IBKR_ENABLED=false` -- see this module's own docstring for why --
    before `_live_scope`'s own `_is_ibkr_connected()` check gets a chance to make a real
    `GET /iserver/auth/status` call against this dev container's ambient `backend/.env`.
    """
    monkeypatch.setenv("FINTRADE_IBKR_ENABLED", "false")
    get_settings.cache_clear()

    sleep_seconds = 0.05

    monkeypatch.setattr(
        dependencies_module,
        "YFinanceProvider",
        lambda: _RacingPrimaryProvider(sleep_seconds=sleep_seconds),
    )
    monkeypatch.setattr(dependencies_module, "StooqProvider", _UnusedFallbackProvider)

    try:
        yield sleep_seconds
    finally:
        get_settings.cache_clear()


class TestRepeatedFastFailWithSlowAbandonedLeg:
    """Repeatedly exercises the exact scenario PR #360's second review round reproduced: a
    fast-failing daily leg returns the response while a slow extended-data leg is still running
    in the background, writing through a real `CachedDataProvider`/`Session`. Every iteration
    must return a clean `404` -- never an unhandled exception escaping the ASGI call stack (what
    `sqlalchemy.exc.IllegalStateChangeError` racing `get_db`'s `db.close()` caused pre-fix)."""

    _ITERATIONS = 40

    def test_many_repeated_requests_never_crash_on_the_shared_session_race(
        self, _shared_engine_session_factories, _racing_providers
    ) -> None:
        _engine, test_session_local = _shared_engine_session_factories
        sleep_seconds = _racing_providers
        client = TestClient(app)

        for _ in range(self._ITERATIONS):
            # Must not raise -- pre-fix, `sqlalchemy.exc.IllegalStateChangeError` propagated out
            # of FastAPI's own dependency-teardown `AsyncExitStack.__aexit__` on a real fraction
            # of iterations, meaning `TestClient.get(...)` itself raised instead of returning a
            # response object at all (see this module's own docstring).
            response = client.get(f"/api/stocks/{_TICKER}/analysis")

            assert response.status_code == 404

        # Let every leg's own background thread (started but abandoned by some earlier
        # iteration -- each iteration's extended-data leg sleeps past that same iteration's own
        # response) finish naturally before asserting on the cache/before this fixture's own
        # teardown disposes the shared engine out from under a still-running thread.
        time.sleep(sleep_seconds * 4)

        # A real, if abandoned, cache write did actually happen -- proving the abandoned leg
        # genuinely ran a real `CachedDataProvider._upsert_extended` commit against its own
        # session to completion, not that it was silently never reached at all. Exactly one row
        # regardless of how many of the `_ITERATIONS` abandoned legs raced to write it (a plain
        # upsert keyed by ticker -- see `_upsert_extended`'s own docstring).
        verification_session = test_session_local()
        try:
            row_count = (
                verification_session.query(func.count(ExtendedDataCacheORM.ticker))
                .filter(ExtendedDataCacheORM.ticker == _TICKER)
                .scalar()
            )
            assert row_count == 1
        finally:
            verification_session.close()
