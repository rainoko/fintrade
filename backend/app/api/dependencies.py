"""Shared FastAPI dependencies for the API routers (app/api/routers/*.py).

Kept separate from app/db/session.py (which only knows about the DB session)
so any router needing market data — the first is GET /api/portfolio's price
enrichment — depends on one composed `DataProvider` rather than each router
wiring up YFinanceProvider/StooqProvider/CachedDataProvider by hand. See the
api-portfolio-get task's `decisions` entry for why this lives here instead of
inline in app/data/cache.py.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.base import DataProvider
from app.data.cache import CachedDataProvider
from app.data.cftc_cot_provider import CFTCCOTProvider
from app.data.fixture_provider import FixtureDataProvider
from app.data.ibkr_data_provider import IBKRDataProvider, IBKRPrimaryDataProvider
from app.data.ibkr_provider import IBKRProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.session import SessionLocal, get_db


def get_data_provider(db: Session = Depends(get_db)) -> DataProvider:
    """The market-data provider used by API routes.

    Normally (``Settings.data_provider_mode == "live"``, the default): IBKR exclusively
    when its gateway is connected/authenticated (`_build_live_data_provider` below,
    `backend-ibkr-primary-data-provider`), otherwise yfinance primary / Stooq fallback
    (docs/Analyse.md §9) — both behind the SQLite read-through cache
    (docs/architecture/Backend.md §7). A fresh pair of provider adapters is constructed
    per request — they're stateless, so this is cheap — while the cache shares the
    request's `db` session.

    When ``FINTRADE_DATA_PROVIDER_MODE=fixture`` is set (only ever done by the
    frontend e2e test suite, see `app.data.fixture_provider`): a deterministic,
    no-network `FixtureDataProvider` instead, bypassing `CachedDataProvider`
    entirely — fixture data is already free/instant to "fetch" and never
    changes, so there's nothing for the cache to usefully do, and skipping it
    keeps the e2e suite's dedicated database free of cache-table rows.

    This single-shared-instance shape is safe for every caller that fully waits on every
    concurrent fetch it starts before returning (e.g. `app.portfolio.pricing
    .enrich_positions_with_price`, `app.api.day_trader_signal._fan_out_per_ticker`'s
    `with ThreadPoolExecutor(...) as executor:` pattern) — the request's `db` (and the
    `CachedDataProvider` wrapping it) is never touched again after the handler returns and
    `get_db`'s `finally: db.close()` runs, because nothing is still running at that point. It
    is **not** safe for a caller that can return (and let `db` close) while a concurrently
    submitted fetch is still in flight — see `get_data_provider_factory` below for that case.
    """
    if get_settings().data_provider_mode == "fixture":
        return FixtureDataProvider()
    return _build_live_data_provider(db)


def _is_ibkr_connected() -> bool:
    """Whether `get_data_provider`/`get_data_provider_factory` should source market data
    from IBKR instead of yfinance/Stooq for this call -- `Settings.ibkr_enabled` AND a
    currently-`available` gateway (`backend-ibkr-primary-data-provider`'s checklist item
    3). Goes through the same process-wide `IBKRProvider` singleton `get_ibkr_provider`
    uses (`_get_ibkr_provider_singleton`) rather than constructing a fresh instance just
    to check status -- that would both discard `get_gateway_status`'s own TTL cache
    (`app.data.ibkr_provider._GATEWAY_STATUS_TTL_SECONDS`) and, if this call ends up using
    IBKR as primary, mean two separate `IBKRProvider` instances backing the same request
    (this check's, and the one `_build_ibkr_primary_data_provider` would otherwise
    construct) with two separate conid/gateway-status caches instead of one shared pair.
    """
    if not get_settings().ibkr_enabled:
        return False
    return _get_ibkr_provider_singleton().get_gateway_status().state == "available"


def _build_live_data_provider(db: Session) -> DataProvider:
    """The non-fixture-mode `DataProvider` composition shared by `get_data_provider` and
    `get_data_provider_factory`'s own live-mode scope, so both pick the same source for
    the same gateway state rather than drifting independently.
    """
    if _is_ibkr_connected():
        return _build_ibkr_primary_data_provider(db)
    return CachedDataProvider(YFinanceProvider(), StooqProvider(), db)


def _build_ibkr_primary_data_provider(db: Session) -> DataProvider:
    """The `IBKRPrimaryDataProvider` composition used while IBKR is connected
    (`backend-ibkr-primary-data-provider`'s checklist items 4/5 -- see that task's
    `decisions` entry for the full rationale):

    - OHLCV: `IBKRDataProvider` wrapped in `CachedDataProvider` as **both** primary and
      fallback. Passing the same instance twice is deliberate, not a typo -- the task's
      own explicit requirement is that a per-call IBKR failure must never fall back to
      yfinance/Stooq while IBKR is connected, so `CachedDataProvider`'s "try primary, on
      `DataProviderUnavailableError` try fallback" logic retrying the *same* IBKR adapter
      on failure (rather than a different source) is exactly the desired behavior: it
      still gets the SQLite OHLCV read-through cache (`app.data.cache._CACHE_TTL`'s 24h
      window) for free, and a genuine failure simply surfaces as `DataProviderUnavailableError`
      (both "primary" and "fallback" attempts report the same underlying failure) rather
      than silently reaching for a different provider.
    - Extended data: delegated whole-sale to the existing cached yfinance/Stooq chain
      (`CachedDataProvider(YFinanceProvider(), StooqProvider(), db)`, unchanged from the
      non-IBKR path) via `IBKRPrimaryDataProvider`, which routes `get_extended_data` to
      this directly rather than through the OHLCV `CachedDataProvider` above -- avoiding a
      second, redundant caching layer around the same `ExtendedDataCacheORM` rows (see
      `IBKRPrimaryDataProvider`'s own docstring).
    """
    ibkr_adapter = IBKRDataProvider(_get_ibkr_provider_singleton())
    ohlcv_provider = CachedDataProvider(ibkr_adapter, ibkr_adapter, db)
    extended_data_provider = CachedDataProvider(YFinanceProvider(), StooqProvider(), db)
    return IBKRPrimaryDataProvider(ohlcv_provider, extended_data_provider)


def get_data_provider_factory() -> Callable[[], AbstractContextManager[DataProvider]]:
    """A `DataProvider`-scope factory for a caller that may abandon an in-flight fetch --
    i.e. return control to FastAPI (letting the request's own `db` session close, per
    `get_db`) while a concurrently submitted fetch against a *different* `DataProvider` call
    is still running in its own thread. Used by `GET /api/stocks/{ticker}/analysis`
    (`app.api.routers.stocks.get_analysis`, see its own docstring and this task's `decisions`
    entry) for its fail-fast concurrent daily/weekly/extended-data fetch.

    Returns a callable that, each time it's called, produces a context manager yielding a
    fresh `DataProvider` and closing whatever it opened on `__exit__` -- entirely independent
    of the request's own `Depends(get_db)` session and of every other `DataProvider` this same
    factory has produced. Concretely (non-fixture mode): each call opens its own
    `SessionLocal()` and wraps it in a fresh `CachedDataProvider`, closing that session itself
    once the caller's own `with` block exits -- regardless of what thread that happens on, or
    whether the request handler that triggered the call has already returned.

    This is the actual fix for the DB-session race PR #360's second review round reproduced
    (`sqlalchemy.exc.IllegalStateChangeError`, real `FastAPI` + `TestClient` + real
    `get_db`/`SessionLocal`, ~30-40% of runs): the earlier `executor.shutdown(wait=False,
    cancel_futures=True)` fix let an abandoned weekly/extended leg keep running in the
    background after the response was returned, and that leg wrote through `CachedDataProvider`
    sharing the exact same `Session` `get_db`'s `finally: db.close()` was about to close on the
    request-handling thread -- a live `Session` touched from two threads at once with no
    coordination between `CachedDataProvider._lock` (per-instance, unaware of `get_db`'s
    teardown) and `get_db` itself (unaware of that lock). Since each `DataProvider` this
    factory produces owns a session nothing else will ever close, there is no longer any
    shared session for an abandoned leg to race -- it simply finishes (or fails) entirely on
    its own, on its own connection, whenever it happens to finish, with nothing else depending
    on that timing. See `app.data.cache.CachedDataProvider`'s own docstring for why this
    per-call-session shape isn't used for `get_data_provider` itself instead: several existing
    callers (`enrich_positions_with_price`, `tests/integration/test_portfolio_pricing_session
    .py`) deliberately rely on the *shared*-session shape there (mid-loop cache commits
    reusing already-loaded ORM rows off the same session without re-`SELECT`ing them,
    `expire_on_commit=False`) -- switching that shared dependency to a per-call session would
    silently defeat that, for callers that don't actually have this factory's problem (they
    already fully wait on their own concurrent fetches before returning).
    """
    if get_settings().data_provider_mode == "fixture":
        fixture_provider = FixtureDataProvider()

        @contextmanager
        def _fixture_scope() -> Iterator[DataProvider]:
            # No DB session at all in fixture mode (see `get_data_provider`'s own docstring) --
            # nothing for an abandoned leg to race, so the same stateless instance is reused.
            yield fixture_provider

        return _fixture_scope

    @contextmanager
    def _live_scope() -> Iterator[DataProvider]:
        db = SessionLocal()
        try:
            yield _build_live_data_provider(db)
        finally:
            db.close()

    return _live_scope


_ibkr_provider_singleton: IBKRProvider | None = None
_ibkr_provider_singleton_lock = threading.Lock()


def _get_ibkr_provider_singleton() -> IBKRProvider:
    """The lazily-constructed, process-wide `IBKRProvider` instance backing
    `get_ibkr_provider` below.

    Uses explicit double-checked locking (`_ibkr_provider_singleton_lock`) rather
    than `@functools.lru_cache(maxsize=1)`: an earlier revision of this function used
    `lru_cache` on the theory that it "gives thread-safe lazy-init for free," matching
    `get_settings()`'s own pattern (app/config.py) -- but that's not actually true for
    what matters here. CPython's `lru_cache` only holds its internal lock around the
    cache dict/linked-list bookkeeping; it releases the lock *before* calling the
    wrapped function and re-acquires it *after*. On a cold cache, two threads that
    both observe a miss each independently execute the factory body -- each
    constructing its own `IBKRProvider`/`httpx.Client`/throttle state -- and each
    thread's call returns its own locally-computed instance, not necessarily the one
    that ends up cached (reproduced empirically during PR #191's review: 20 concurrent
    threads racing a cold `lru_cache` -> 20 separate factory executions, 20 distinct
    instances returned to callers). `get_settings()` gets away with the identical
    `lru_cache` pattern only because a duplicated `Settings` object during that race
    window is harmless (no meaningful per-instance mutable state); `IBKRProvider` has
    exactly the per-instance state (HTTP client, scanner-params cache, `run_scanner`
    throttle) this singleton exists to protect, so a duplicate construction is a real
    correctness bug, not a harmless race. The explicit lock below closes that window:
    the fast path (no lock) only applies once the singleton is definitely set; every
    thread that might be racing a cold cache serializes on the lock and re-checks
    before constructing, so only one `IBKRProvider` is ever built. Tests reset this
    between runs via `_reset_ibkr_provider_singleton_for_tests()` (see
    tests/unit/api/test_dependencies.py's autouse fixture).
    """
    global _ibkr_provider_singleton
    if _ibkr_provider_singleton is None:
        with _ibkr_provider_singleton_lock:
            if _ibkr_provider_singleton is None:
                _ibkr_provider_singleton = IBKRProvider(base_url=get_settings().ibkr_base_url)
    return _ibkr_provider_singleton


def _reset_ibkr_provider_singleton_for_tests() -> None:
    """Test-only reset for `_ibkr_provider_singleton` (mirrors `get_settings.cache_clear()`).

    A plain `monkeypatch.setattr(..., None)` can't safely stand in for this: the
    singleton is mutated by application code via a `global` assignment inside the lock
    above, not by anything monkeypatch itself touched, so monkeypatch's teardown
    wouldn't reliably restore a clean `None` state for the next test. Goes through the
    same lock as the real getter so a reset can never race a concurrent construction.
    """
    global _ibkr_provider_singleton
    with _ibkr_provider_singleton_lock:
        _ibkr_provider_singleton = None


def get_ibkr_provider() -> Iterator[IBKRProvider | None]:
    """The optional IBKR Client Portal Web API provider (docs/tasks/
    backend-ibkr-data-provider.json) -- hourly bars + the market scanner, entirely
    separate from `get_data_provider`'s primary/fallback `DataProvider` chain above,
    since `IBKRProvider` doesn't implement that protocol (see its own module docstring
    for why).

    Yields `None` when `Settings.ibkr_enabled` is `False` (the default, and the only
    value in any environment without a locally-running, authenticated IB Gateway) --
    every existing route keeps working identically whether or not this returns `None`,
    since nothing yet depends on this provider (see this task's `decisions` entry for
    why: this task's own checklist scopes it to the provider class itself, not a new
    consuming endpoint).

    Unlike `get_data_provider` above, this does **not** construct a fresh `IBKRProvider`
    per request: a process-wide singleton (`_get_ibkr_provider_singleton` above) is
    created once (lazily, on first use while enabled) and reused across every
    subsequent call, never closed at the end of a request. `IBKRProvider`'s
    scanner-params TTL cache and `run_scanner` 1-req/sec throttle are both in-memory
    instance state -- a per-request instance (closed at the end of every request) would
    silently defeat both, providing zero cross-request rate-limit protection despite
    the class's own design assuming one instance persists across calls. The singleton's
    HTTP client is intentionally never closed here; it lives for the app process's
    lifetime, same as e.g. a module-level SQLAlchemy engine would.
    """
    if not get_settings().ibkr_enabled:
        yield None
        return

    yield _get_ibkr_provider_singleton()


def get_cftc_cot_provider() -> CFTCCOTProvider:
    """The CFTC Commitments of Traders (COT) provider used by `app.api.routers.cftc`
    (docs/tasks/backend-cftc-cot-data.json).

    A fresh instance per request, same as `get_data_provider`'s yfinance/Stooq adapters:
    `CFTCCOTProvider` is stateless (no rate-limit/session state to preserve across
    requests, unlike `IBKRProvider`), so there's nothing a shared singleton would buy here
    -- see this task's `decisions` entry.
    """
    return CFTCCOTProvider()
