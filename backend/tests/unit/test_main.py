"""Tests for app.main's background lifespan tasks: the IBKR /tickle keep-alive loop
(docs/tasks/backend-ibkr-tickle-keepalive.json) and the CFTC COT cache's weekly
scheduled refresh loop (docs/tasks/backend-cftc-cot-caching-scheduler.json).

Every test here mocks `Base.metadata.create_all` (app.main's own DB bootstrap step,
already exercised elsewhere) so exercising `lifespan()` directly never touches the real
on-disk database, and mocks `app.main.get_ibkr_provider` (rather than flipping
`Settings.ibkr_enabled` via the real environment) so these tests control the gate
directly -- this app's constraint that `FINTRADE_IBKR_ENABLED` stays `false` throughout
(docs/architecture/Backend.md §8) is never touched here, and no test in this module ever
lets a real `IBKRProvider` make an HTTP call. `TestLifespanCftcCotRefreshLoop` below
additionally patches `app.main.SessionLocal` to an in-memory SQLite database (see its own
fixture) so `_refresh_cftc_cot_cache_if_stale`'s own DB session work never touches the
real on-disk database either, and stubs/mocks `CFTCCOTProvider` so no test makes a live
call to the CFTC's Socrata endpoint.
"""

import asyncio
import threading
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
from app.config import get_settings
from app.data.cftc_cot_cache import CFTCCOTCache
from app.data.cftc_cot_provider import COT_MARKETS, COTWeeklyReport
from app.data.exceptions import DataProviderUnavailableError
from app.data.ibkr_provider import IBKRUnavailableError
from app.db.models import Base, CFTCCOTCacheORM
from app.main import app, lifespan
from app.time_utils import utcnow


@pytest.fixture(autouse=True)
def _skip_db_bootstrap(mocker):
    """Every test below calls `lifespan()` directly (not through `TestClient`, which
    never triggers lifespan events unless used as a context manager -- see
    tests/conftest.py's plain `TestClient(app)` fixture), so without this, each test
    would run `Base.metadata.create_all(bind=engine)` against the real on-disk database
    `app.db.session.engine` points at."""
    mocker.patch("app.main.Base.metadata.create_all")


@pytest.fixture(autouse=True)
def _stub_cftc_refresh_check(mocker):
    """`_cftc_cot_refresh_loop` now runs `_check_and_refresh_cftc_cot_cache_once`
    immediately on startup, not just on each subsequent wake-up (PR #380 review --
    a cache already stale at restart must not wait a full check interval for
    correction). Every test in this module calls `lifespan()` directly, so without this
    stub, every test *outside* `TestLifespanCftcCotRefreshLoop` (which doesn't otherwise
    care about the CFTC loop's own behavior) would immediately construct a real
    `CFTCCOTProvider` and hit the real on-disk DB/CFTC's live Socrata endpoint the moment
    `lifespan()` is entered. `TestLifespanCftcCotRefreshLoop` overrides this with its own
    no-op fixture of the same name (pytest's standard fixture-override-by-name
    mechanism) to exercise the real thing, mocking only the specific pieces
    (`get_cftc_cot_provider`, `SessionLocal`) each of its own tests needs.
    """
    mocker.patch("app.main._check_and_refresh_cftc_cot_cache_once", new=mocker.AsyncMock())


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.01) -> None:
    """Poll `predicate()` on a real timer until it's true, instead of a fixed count of
    `asyncio.sleep(0)` cooperative yields.

    `_ibkr_tickle_loop` calls `IBKRProvider.tickle()` via `asyncio.to_thread` -- a real
    thread-pool round trip -- so a fixed iteration count of bare cooperative yields isn't
    guaranteed to let it complete even once (let alone twice) before the test gives up;
    under load (coverage instrumentation, a concurrent test run) that round trip can take
    longer than 200 `sleep(0)`s do. Sleeping a real, if tiny, `interval` between checks
    gives the worker thread actual wall-clock time to run, and `asyncio.wait_for` still
    bounds the wait so a genuine regression (the loop never calling `tickle()` at all)
    fails promptly instead of hanging.
    """

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_poll(), timeout=timeout)


class TestLifespanIbkrTickleGate:
    def test_disabled_never_starts_an_ibkr_task_or_touches_the_gateway(self, mocker) -> None:
        """`get_ibkr_provider` yielding `None` (the default -- `Settings.ibkr_enabled`
        is `False`) must mean no IBKR tickle background task is ever created, per this
        task's own constraint that the lifespan task is a genuine no-op while disabled.

        Uses `mocker.spy` (not a full `mocker.patch`) on `asyncio.create_task` so the
        always-on CFTC COT refresh task (`backend-cftc-cot-caching-scheduler`, unrelated
        to this gate) is still genuinely created and can be cleanly awaited/cancelled by
        `lifespan`'s own `finally` block -- a full mock would make that `await` raise
        `TypeError` (a `MagicMock` isn't awaitable). It's never exercised beyond its
        initial `asyncio.sleep` in this test's short real-time window, so this touches
        neither the network nor the database.
        """
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([None]))
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                pass

        asyncio.run(_run())

        # Exactly one task created (the always-on CFTC refresh loop) -- no IBKR tickle task.
        assert create_task_spy.call_count == 1

    def test_enabled_starts_a_task_that_calls_tickle(self, mocker) -> None:
        fake_provider = mocker.Mock()
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        # 0s so the loop's very first `asyncio.sleep` yields control without any real delay.
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            async with lifespan(app):
                await _wait_until(lambda: fake_provider.tickle.called)

        asyncio.run(_run())

        fake_provider.tickle.assert_called()

    def test_enabled_task_is_cancelled_cleanly_on_shutdown(self, mocker) -> None:
        fake_provider = mocker.Mock()
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        # Long enough that the loop is guaranteed to still be sleeping (not mid-tickle)
        # when the `async with` block below exits and triggers shutdown.
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 100.0)
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                await asyncio.sleep(0)

        asyncio.run(_run())

        # `spy_return_list[0]` (not `spy_return`, which is the *last* call's return value)
        # is this test's IBKR tickle task specifically: `lifespan` creates it before the
        # always-on CFTC COT refresh task (`backend-cftc-cot-caching-scheduler`), so it's
        # always the first of the two `asyncio.create_task` calls here.
        task = create_task_spy.spy_return_list[0]
        assert task is not None
        assert task.cancelled()
        fake_provider.tickle.assert_not_called()

    def test_shutdown_does_not_block_on_an_in_flight_tickle_call(self, mocker) -> None:
        """`backend-ibkr-tickle-keepalive-followups`: exercises cancelling `tickle_task`
        while it's mid-`await asyncio.to_thread(provider.tickle)` (an HTTP request already
        dispatched to a worker thread) -- previously untested; only the "still sleeping"
        cancellation path (`test_enabled_task_is_cancelled_cleanly_on_shutdown` above) was
        covered.

        Verified with a real-timing repro (see this task's `decisions`) that
        `lifespan()`'s `await tickle_task` in its `finally` block does *not* block on that
        in-flight call: `asyncio.to_thread` awaits a plain `asyncio.Future` wrapping the
        executor's `concurrent.futures.Future`, and a plain `Future.cancel()` marks itself
        cancelled immediately regardless of whether the underlying thread-pool work can
        actually be stopped -- so `CancelledError` propagates into the `await` right away.
        The worker thread itself isn't interrupted; it keeps running `provider.tickle()`
        to completion in the background, orphaned and discarded (bounded here by a short
        real `time.sleep`, never a live network call), which is harmless since nothing
        ever reads its result.
        """
        sleep_seconds = 0.2
        started = threading.Event()
        tickle_start = 0.0

        def _slow_tickle() -> None:
            nonlocal tickle_start
            tickle_start = time.monotonic()
            started.set()
            time.sleep(sleep_seconds)

        fake_provider = mocker.Mock()
        fake_provider.tickle.side_effect = _slow_tickle
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> float:
            async with lifespan(app):
                # `started` is set before the in-flight `time.sleep` below even begins, so
                # waiting on it and then immediately falling out of this `async with`
                # block reliably triggers `tickle_task.cancel()` while that sleep --
                # standing in for the real blocking HTTP round trip -- is still running in
                # the worker thread.
                await _wait_until(lambda: started.is_set())
            # Measured here, inside the coroutine, before `asyncio.run`'s own outer
            # teardown (which does wait for the default executor's threads to drain) has
            # a chance to run -- this isolates exactly how long `lifespan()`'s own
            # `finally` block took.
            return time.monotonic() - tickle_start

        elapsed_since_tickle_started = asyncio.run(_run())

        # `lifespan()`'s shutdown returned well before the in-flight call's sleep did --
        # it did not block waiting for that worker thread.
        assert elapsed_since_tickle_started < sleep_seconds * 0.5
        # `spy_return_list[0]` is this test's IBKR tickle task specifically -- see
        # `test_enabled_task_is_cancelled_cleanly_on_shutdown`'s identical comment above.
        task = create_task_spy.spy_return_list[0]
        assert task is not None
        assert task.cancelled()
        fake_provider.tickle.assert_called_once()

    def test_enabled_logs_and_keeps_looping_when_tickle_fails(self, mocker, caplog) -> None:
        """A single failed `/tickle` call (gateway down, session actually expired) must
        not kill the loop -- `GET /api/ibkr/status` already exists for a caller to
        observe the resulting state, so this loop's job is only to keep pinging."""
        fake_provider = mocker.Mock()
        fake_provider.tickle.side_effect = IBKRUnavailableError("gateway unreachable")
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            with caplog.at_level("WARNING", logger="app.main"):
                async with lifespan(app):
                    await _wait_until(lambda: fake_provider.tickle.call_count >= 2)

        asyncio.run(_run())

        assert fake_provider.tickle.call_count >= 2
        assert "IBKR /tickle keep-alive call failed" in caplog.text

    def test_enabled_logs_and_keeps_looping_on_a_non_ibkr_exception(self, mocker, caplog) -> None:
        """`backend-ibkr-tickle-keepalive-followups`: `provider.tickle()`'s three raise
        sites are exhaustively `IBKRUnavailableError` today, but a catch narrowed to that
        one type is a latent trap -- if `tickle()` ever raised anything else, the loop
        would exit with that exception stored on the task, `tickle_task.cancel()` in
        `lifespan()`'s `finally` would be a no-op against an already-done task, and
        `await tickle_task` there would re-raise the original exception straight out of
        `lifespan()`'s own `finally` block. This must not happen: an unexpected exception
        (a bare `ValueError` here, standing in for anything that isn't
        `IBKRUnavailableError`) must be logged and the loop must keep running, exactly
        like the already-covered `IBKRUnavailableError` case above, and `lifespan()` must
        exit cleanly (no exception escaping `_run`) on shutdown."""
        fake_provider = mocker.Mock()
        fake_provider.tickle.side_effect = ValueError("some unexpected failure")
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([fake_provider]))
        mocker.patch("app.main._IBKR_TICKLE_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            with caplog.at_level("WARNING", logger="app.main"):
                async with lifespan(app):
                    await _wait_until(lambda: fake_provider.tickle.call_count >= 2)

        asyncio.run(_run())

        assert fake_provider.tickle.call_count >= 2
        assert "IBKR /tickle keep-alive call failed" in caplog.text


class TestLifespanCftcCotRefreshLoop:
    """`_cftc_cot_refresh_loop`/`_refresh_cftc_cot_cache_if_stale`
    (docs/tasks/backend-cftc-cot-caching-scheduler.json) -- the weekly-cadence scheduled
    background refresh for the CFTC COT cache (`app.data.cftc_cot_cache.CFTCCOTCache`).
    """

    @pytest.fixture(autouse=True)
    def _stub_cftc_refresh_check(self):
        """Overrides the module-level stub of the same name above -- this class exists
        specifically to exercise `_check_and_refresh_cftc_cot_cache_once`'s real
        behavior, each test instead mocking only the specific pieces it needs
        (`get_cftc_cot_provider`, `SessionLocal` via `session_factory`)."""
        return

    @pytest.fixture(autouse=True)
    def _disable_ibkr(self, mocker):
        """No test in this class cares about the IBKR tickle task -- disabling it keeps
        each test's `asyncio.create_task` call count down to exactly the one CFTC refresh
        task, so `create_task_spy.spy_return`/`.call_count` (where used) is unambiguous."""
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([None]))

    @pytest.fixture
    def session_factory(self, mocker):
        """An in-memory SQLite `sessionmaker`, patched in as `app.main.SessionLocal` --
        `StaticPool` keeps the one in-memory database alive across every `SessionLocal()`
        call this fixture's consumers make, matching `tests/integration/conftest.py`'s own
        `db_session` fixture rationale. Returned (not just patched in) so a test can seed
        or inspect cache rows directly, through the exact same engine
        `_refresh_cftc_cot_cache_if_stale` itself will use.
        """
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        # Not `Base.metadata.create_all(engine)`: this module's `_skip_db_bootstrap`
        # autouse fixture above patches that exact bound method (an instance attribute on
        # the one `Base.metadata` object shared by every caller, including this one) to a
        # no-op for every test in this module, so calling it here would silently create no
        # tables at all. Creating each table directly sidesteps that patched attribute
        # entirely.
        for table in Base.metadata.tables.values():
            table.create(engine, checkfirst=True)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        mocker.patch("app.main.SessionLocal", factory)
        return factory

    @staticmethod
    def _report(report_date: str = "2026-09-15") -> COTWeeklyReport:
        return COTWeeklyReport(
            report_date=date.fromisoformat(report_date),
            market_and_exchange_name="GOLD - COMMODITY EXCHANGE INC.",
            open_interest=100_000,
            commercial_long=40_000,
            commercial_short=30_000,
            large_speculator_long=35_000,
            large_speculator_short=45_000,
            small_speculator_long=10_000,
            small_speculator_short=12_000,
        )

    def test_refreshes_immediately_on_startup_without_waiting_for_the_first_sleep(
        self, mocker, session_factory
    ) -> None:
        """PR #380 review: a cache already stale when the app restarts (e.g. after any
        downtime longer than `_CFTC_COT_CACHE_MAX_AGE`) must not wait a full
        `_CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS` before being corrected -- unlike
        `_ibkr_tickle_loop`, where sleeping before the first tickle is harmless. The check
        interval here is deliberately long (a real wait would time this test out via
        `_wait_until`'s bound) to prove the refresh runs *before* the loop's first
        `asyncio.sleep`, not only after it.
        """
        reports_by_market = {key: [self._report()] for key in COT_MARKETS}
        fake_provider = mocker.Mock()
        fake_provider.get_all_recent.return_value = reports_by_market
        mocker.patch("app.main.get_cftc_cot_provider", return_value=fake_provider)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 3600.0)

        async def _run() -> None:
            async with lifespan(app):
                await _wait_until(lambda: fake_provider.get_all_recent.called)

        asyncio.run(_run())

        fake_provider.get_all_recent.assert_called_once()

    def test_refreshes_on_a_cold_cache(self, mocker, session_factory) -> None:
        """An empty cache (the state at app startup, before this loop has ever run) is
        due for a refresh on this loop's very first check -- `CFTCCOTCache.is_stale`
        returns `True` with no cached rows at all."""
        reports_by_market = {key: [self._report()] for key in COT_MARKETS}
        fake_provider = mocker.Mock()
        fake_provider.get_all_recent.return_value = reports_by_market
        mocker.patch("app.main.get_cftc_cot_provider", return_value=fake_provider)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            async with lifespan(app):
                await _wait_until(lambda: fake_provider.get_all_recent.called)

        asyncio.run(_run())

        fake_provider.get_all_recent.assert_called()
        session = session_factory()
        try:
            cached = CFTCCOTCache(session).get_cached_reports()
        finally:
            session.close()
        assert cached is not None
        assert cached["gold"][0].commercial_long == 40_000

    def test_skips_refresh_when_cache_is_already_fresh(self, mocker, session_factory) -> None:
        """A cache whose newest fetch is well within `_CFTC_COT_CACHE_MAX_AGE` must not
        trigger a live CFTC call -- this loop's whole point is to avoid a round trip on
        every wake-up once the cache is actually fresh."""
        session = session_factory()
        try:
            cache = CFTCCOTCache(session)
            cache.refresh({key: [self._report()] for key in COT_MARKETS})
        finally:
            session.close()

        fake_provider = mocker.Mock()
        mocker.patch("app.main.get_cftc_cot_provider", return_value=fake_provider)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 0.0)
        refresh_spy = mocker.spy(app_main, "_refresh_cftc_cot_cache_if_stale")

        async def _run() -> None:
            async with lifespan(app):
                await _wait_until(lambda: refresh_spy.call_count >= 2)

        asyncio.run(_run())

        assert refresh_spy.call_count >= 2
        fake_provider.get_all_recent.assert_not_called()

    def test_logs_and_keeps_looping_when_provider_fails(self, mocker, session_factory, caplog) -> None:
        """A cache-miss (empty cache) refresh attempt that fails (CFTC request itself
        fails) must be logged and must not kill the loop -- the on-demand `GET
        /api/cftc/cot` read-through fallback already handles the "never successfully
        populated" case, so this loop's only job is to keep trying."""
        fake_provider = mocker.Mock()
        fake_provider.get_all_recent.side_effect = DataProviderUnavailableError("CFTC unreachable")
        mocker.patch("app.main.get_cftc_cot_provider", return_value=fake_provider)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 0.0)

        async def _run() -> None:
            with caplog.at_level("WARNING", logger="app.main"):
                async with lifespan(app):
                    await _wait_until(lambda: fake_provider.get_all_recent.call_count >= 2)

        asyncio.run(_run())

        assert fake_provider.get_all_recent.call_count >= 2
        assert "CFTC COT cache refresh failed" in caplog.text

    def test_cancelled_cleanly_on_shutdown(self, mocker, session_factory) -> None:
        """Mocks `get_cftc_cot_provider` (unlike `TestLifespanIbkrTickleGate`'s identical
        IBKR-side test, which has no such mock to make): the loop's now-immediate
        startup check (see `_stub_cftc_refresh_check` override above) would otherwise
        construct a real `CFTCCOTProvider` and, since `session_factory`'s cache starts
        empty, dispatch a real live CFTC HTTP call from a background thread before this
        test's own cancellation ever reaches it."""
        fake_provider = mocker.Mock()
        fake_provider.get_all_recent.return_value = {key: [self._report()] for key in COT_MARKETS}
        mocker.patch("app.main.get_cftc_cot_provider", return_value=fake_provider)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 100.0)
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                await asyncio.sleep(0)

        asyncio.run(_run())

        assert create_task_spy.call_count == 1
        task = create_task_spy.spy_return_list[0]
        assert task is not None
        assert task.cancelled()

    def test_shutdown_does_not_block_on_an_in_flight_refresh_call(self, mocker) -> None:
        """`backend-cftc-cot-caching-scheduler-followups`: mirrors
        `TestLifespanIbkrTickleGate.test_shutdown_does_not_block_on_an_in_flight_tickle_call`
        for this loop's identical `asyncio.to_thread` + `Future.cancel()` cancellation
        mechanism, for parity and to guard against a future divergence between the two
        loops' shutdown behavior -- previously untested for this loop specifically.

        Patches `app.main._refresh_cftc_cot_cache_if_stale` itself (rather than going
        through a real DB session) to a slow, blocking stand-in so this test exercises
        only the cancellation timing, not the refresh logic already covered by the other
        tests in this class.
        """
        sleep_seconds = 0.2
        started = threading.Event()
        refresh_start = 0.0

        def _slow_refresh(provider) -> None:
            nonlocal refresh_start
            refresh_start = time.monotonic()
            started.set()
            time.sleep(sleep_seconds)

        mocker.patch("app.main._refresh_cftc_cot_cache_if_stale", side_effect=_slow_refresh)
        mocker.patch("app.main._CFTC_COT_REFRESH_CHECK_INTERVAL_SECONDS", 0.0)
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> float:
            async with lifespan(app):
                # `started` is set before the in-flight `time.sleep` below even begins, so
                # waiting on it and then immediately falling out of this `async with` block
                # reliably triggers `cftc_cot_refresh_task.cancel()` while that sleep --
                # standing in for the real blocking CFTC HTTP round trip/DB work -- is
                # still running in the worker thread.
                await _wait_until(lambda: started.is_set())
            # Measured here, inside the coroutine, before `asyncio.run`'s own outer teardown
            # (which does wait for the default executor's threads to drain) has a chance to
            # run -- this isolates exactly how long `lifespan()`'s own `finally` block took.
            return time.monotonic() - refresh_start

        elapsed_since_refresh_started = asyncio.run(_run())

        # `lifespan()`'s shutdown returned well before the in-flight call's sleep did -- it
        # did not block waiting for that worker thread.
        assert elapsed_since_refresh_started < sleep_seconds * 0.5
        task = create_task_spy.spy_return_list[0]
        assert task is not None
        assert task.cancelled()

    def test_is_stale_true_right_at_max_age_boundary(self, session_factory) -> None:
        """`CFTCCOTCache.is_stale` itself (exercised directly, not through the loop): a
        cache whose newest fetch is exactly `max_age` old (not strictly older) still
        counts as stale -- a `>=` boundary, not `>`, so a refresh is never silently
        skipped for exactly one check cycle right at the threshold."""
        session = session_factory()
        try:
            cache = CFTCCOTCache(session)
            cache.refresh({key: [self._report()] for key in COT_MARKETS})
            # Back-date every row's fetched_at by exactly 6 days (this task's own chosen
            # `_CFTC_COT_CACHE_MAX_AGE`) to land precisely on the boundary.
            max_age = timedelta(days=6)
            boundary = utcnow() - max_age
            session.query(CFTCCOTCacheORM).update({CFTCCOTCacheORM.fetched_at: boundary})
            session.commit()

            assert cache.is_stale(max_age) is True
            assert cache.is_stale(max_age + timedelta(seconds=1)) is False
        finally:
            session.close()


class TestLifespanCftcCotFixtureModeGate:
    """PR #380 review (round 3, a genuine blocking finding from a code-review pass that
    completed after an earlier round had already been accepted): `_cftc_cot_refresh_loop`
    must never start while `Settings.data_provider_mode == "fixture"`. Its
    immediate-on-startup check (`_check_and_refresh_cftc_cot_cache_once`) would otherwise
    construct a real `CFTCCOTProvider` and make a genuine live HTTPS call to CFTC's public
    Socrata endpoint on every single app process start -- including every frontend e2e run
    (`frontend/playwright.config.ts` sets `FINTRADE_DATA_PROVIDER_MODE=fixture`
    specifically to guarantee zero live network calls) and every plain local `uvicorn`
    boot -- directly violating CLAUDE.md's Testing standard. There is no CFTC fixture
    provider to refresh the cache against instead (unlike OHLCV's `FixtureDataProvider`),
    so "don't start the loop at all" is the correct fixture-mode behavior, matching the
    IBKR-disabled gate's own shape (`TestLifespanIbkrTickleGate` above).
    """

    @pytest.fixture(autouse=True)
    def _disable_ibkr(self, mocker):
        """Keeps each test's `asyncio.create_task` call count unambiguous (0 or 1,
        attributable only to the CFTC loop), same rationale as
        `TestLifespanCftcCotRefreshLoop._disable_ibkr` above."""
        mocker.patch("app.main.get_ibkr_provider", return_value=iter([None]))

    def test_fixture_mode_never_starts_the_refresh_task_or_constructs_a_provider(
        self, monkeypatch, mocker
    ) -> None:
        """The regression test for the live-call bug itself: in fixture mode, no task is
        created at all, and `get_cftc_cot_provider()` -- the only thing that would
        construct a real `CFTCCOTProvider` and make the live HTTPS call -- is never even
        called."""
        monkeypatch.setenv("FINTRADE_DATA_PROVIDER_MODE", "fixture")
        get_settings.cache_clear()
        cftc_provider_dependency = mocker.patch("app.main.get_cftc_cot_provider")
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                await asyncio.sleep(0)

        try:
            asyncio.run(_run())
        finally:
            get_settings.cache_clear()  # don't leak the monkeypatched setting into other tests

        assert create_task_spy.call_count == 0
        cftc_provider_dependency.assert_not_called()

    def test_live_mode_still_starts_the_refresh_task(self, mocker) -> None:
        """Confirms the gate is genuinely conditional on `data_provider_mode`, not an
        accidental always-off -- the default (`live`) mode, which every test in
        `TestLifespanCftcCotRefreshLoop` above already implicitly relies on, must still
        start exactly one task."""
        mocker.patch("app.main._check_and_refresh_cftc_cot_cache_once", new=mocker.AsyncMock())
        create_task_spy = mocker.spy(asyncio, "create_task")

        async def _run() -> None:
            async with lifespan(app):
                await asyncio.sleep(0)

        asyncio.run(_run())

        assert create_task_spy.call_count == 1
