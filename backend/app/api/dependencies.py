"""Shared FastAPI dependencies for the API routers (app/api/routers/*.py).

Kept separate from app/db/session.py (which only knows about the DB session)
so any router needing market data — the first is GET /api/portfolio's price
enrichment — depends on one composed `DataProvider` rather than each router
wiring up YFinanceProvider/StooqProvider/CachedDataProvider by hand. See the
api-portfolio-get task's `decisions` entry for why this lives here instead of
inline in app/data/cache.py.
"""

import threading
from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.base import DataProvider
from app.data.cache import CachedDataProvider
from app.data.fixture_provider import FixtureDataProvider
from app.data.ibkr_provider import IBKRProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.session import get_db


def get_data_provider(db: Session = Depends(get_db)) -> DataProvider:
    """The market-data provider used by API routes.

    Normally (``Settings.data_provider_mode == "live"``, the default): yfinance
    primary, Stooq fallback (docs/Analyse.md §9), both behind the SQLite
    read-through cache (docs/architecture/Backend.md §7). A fresh pair of
    provider adapters is constructed per request — they're stateless, so this
    is cheap — while the cache shares the request's `db` session.

    When ``FINTRADE_DATA_PROVIDER_MODE=fixture`` is set (only ever done by the
    frontend e2e test suite, see `app.data.fixture_provider`): a deterministic,
    no-network `FixtureDataProvider` instead, bypassing `CachedDataProvider`
    entirely — fixture data is already free/instant to "fetch" and never
    changes, so there's nothing for the cache to usefully do, and skipping it
    keeps the e2e suite's dedicated database free of cache-table rows.
    """
    if get_settings().data_provider_mode == "fixture":
        return FixtureDataProvider()
    return CachedDataProvider(YFinanceProvider(), StooqProvider(), db)


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
