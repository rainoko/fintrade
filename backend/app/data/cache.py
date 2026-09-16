"""SQLite-backed read-through OHLCV cache (docs/architecture/Backend.md §7,
docs/Architecture.md §3).

``CachedDataProvider`` wraps a primary + fallback ``DataProvider`` (in
practice ``YFinanceProvider`` and ``StooqProvider``) with ``OHLCVCacheORM``
(app/db/models.py): cached rows are served straight from SQLite when fresh,
a source fetch is only made on a miss or when the cache has gone stale, and
that source call itself falls back from primary to fallback on an
availability failure per docs/Analyse.md §9. See this task's `decisions`
entry (docs/tasks/data-cache.json) for the freshness policy, the "date
range" reading, and the fallback scope, all of which are shaped by the
`DataProvider` protocol (app/data/base.py) taking no date-range argument.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.data.base import DataProvider
from app.data.exceptions import DataProviderUnavailableError
from app.db.models import OHLCVCacheORM

logger = logging.getLogger(__name__)

_INTERVAL_DAILY = "daily"
_INTERVAL_WEEKLY = "weekly"

_COLUMNS = ("open", "high", "low", "close", "volume")

# A cached ticker/interval is served straight from SQLite -- no source call
# at all -- as long as its most recent fetch is within this window; past it,
# it's treated as stale and refreshed. See this task's `decisions` entry for
# why this is a flat TTL rather than a trading-calendar-aware "is this the
# latest session" check.
_CACHE_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    """Naive UTC 'now', matching how `OHLCVCacheORM.fetched_at` is stored/compared."""
    return datetime.now(UTC).replace(tzinfo=None)


class CachedDataProvider(DataProvider):
    """Read-through OHLCV cache in front of a primary + fallback `DataProvider`."""

    def __init__(self, primary: DataProvider, fallback: DataProvider, db: Session) -> None:
        self._primary = primary
        self._fallback = fallback
        self._db = db

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`, from cache if fresh, else fetched and cached.

        Raises:
            TickerNotFoundError / InsufficientHistoryError: as raised by the
                primary provider (not masked by attempting the fallback --
                see this task's `decisions` entry).
            DataProviderUnavailableError: both primary and fallback providers
                failed and no usable cache exists.
        """
        return self._get(ticker, interval=_INTERVAL_DAILY)

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`. Same cache/fallback/error behavior as
        `get_daily_ohlcv`, cached under a distinct `interval` key.
        """
        return self._get(ticker, interval=_INTERVAL_WEEKLY)

    def _get(self, ticker: str, *, interval: str) -> pd.DataFrame:
        cached_rows = self._read_cache(ticker, interval)
        if cached_rows and self._is_fresh(cached_rows):
            return self._rows_to_frame(cached_rows)

        fetched = self._fetch_from_source(ticker, interval)
        # Cast volume to float here so the cache-miss return value matches the
        # cache-hit path's dtype (`_rows_to_frame` reads it back out of
        # `OHLCVCacheORM.volume`, a `Float` column, as float64) -- the raw
        # provider frame's volume column is int64. Not externally observable
        # today (app/api/schemas.py declares `volume: float` and Pydantic
        # coerces either dtype at the response boundary), but keeps the two
        # code paths internally consistent for any future caller that
        # branches on dtype. See this task's `decisions` entry.
        fetched["volume"] = fetched["volume"].astype("float64")
        self._upsert(ticker, interval, fetched)
        return fetched

    def _read_cache(self, ticker: str, interval: str) -> list[OHLCVCacheORM]:
        """All currently-cached rows for `ticker`/`interval` -- i.e. whatever date
        range is already cached, since the `DataProvider` protocol itself has no
        caller-supplied date-range argument to narrow this to (see module docstring).
        """
        return (
            self._db.query(OHLCVCacheORM)
            .filter(OHLCVCacheORM.ticker == ticker, OHLCVCacheORM.interval == interval)
            .order_by(OHLCVCacheORM.date)
            .all()
        )

    @staticmethod
    def _is_fresh(rows: list[OHLCVCacheORM]) -> bool:
        """Whether `rows` (all cached rows for one ticker/interval) are still within
        `_CACHE_TTL`, judged by the most recent `fetched_at` among them.

        Known latent gap (documented, not fixed -- see this task's `decisions`
        entry): this derives freshness from `max(fetched_at)` across every cached
        row, so if a source's returned history window ever *shrank* between calls
        (dropping some previously-cached dates), the rows that fell out of the new
        window would never be individually revalidated or evicted, yet would still
        read as fresh forever because newer sibling rows dominate the max. Doesn't
        manifest under either real `DataProvider` today (`YFinanceProvider` and
        `StooqProvider` both always return full, un-windowed history, so `_upsert`
        re-stamps every cached row together on each refresh -- none is ever left
        behind). Would need a per-(ticker, interval) `cache_refreshed_at` tracked
        independently of individual row timestamps, and/or evicting rows that drop
        out of a fresh fetch, if a future `DataProvider` ever supports windowed
        fetches.
        """
        most_recent_fetch = max(row.fetched_at for row in rows)
        return _utcnow() - most_recent_fetch < _CACHE_TTL

    def _fetch_from_source(self, ticker: str, interval: str) -> pd.DataFrame:
        """Fetch full history from the primary provider, falling back to the
        secondary one only on a `DataProviderUnavailableError` -- an
        availability failure (rate limit, network error, unexpected
        response), not a per-ticker outcome like an unknown ticker or
        insufficient history, which propagate immediately without trying
        the fallback (docs/Analyse.md §9; see this task's `decisions` entry).
        """
        primary_failure: str | None = None
        try:
            return self._call(self._primary, ticker, interval)
        except DataProviderUnavailableError as primary_exc:
            # Logged (not silently discarded) so the primary's own failure reason
            # survives even when the fallback succeeds. Captured into a plain str
            # (`primary_failure`) rather than kept as an exception object because
            # Python deletes an `except ... as name` binding at the end of its own
            # except block -- referencing `primary_exc` itself below (outside this
            # block) would raise NameError. See this task's `decisions` entry.
            primary_failure = str(primary_exc)
            logger.warning(
                "Primary data provider failed for %r (%s), falling back: %s",
                ticker,
                interval,
                primary_failure,
            )

        try:
            return self._call(self._fallback, ticker, interval)
        except DataProviderUnavailableError as fallback_exc:
            raise DataProviderUnavailableError(
                f"Both primary and fallback providers failed for {ticker!r} ({interval}): "
                f"primary={primary_failure}, fallback={fallback_exc}"
            ) from fallback_exc

    @staticmethod
    def _call(provider: DataProvider, ticker: str, interval: str) -> pd.DataFrame:
        if interval == _INTERVAL_DAILY:
            return provider.get_daily_ohlcv(ticker)
        return provider.get_weekly_ohlcv(ticker)

    def _upsert(self, ticker: str, interval: str, frame: pd.DataFrame) -> None:
        """Insert new rows / update existing ones (by ticker+date+interval primary
        key) from a freshly fetched `frame`, stamping all of them with the same
        `fetched_at`. This is only reached when the cache was empty or stale for
        this ticker/interval, so it naturally covers just the missing/stale range
        even though it's implemented as one full upsert pass -- the provider
        adapters don't support fetching a narrower date range (see module docstring).

        Existing rows are bulk-loaded once (a single query keyed by this
        ticker/interval, the same query `_read_cache` already runs) rather than
        looked up one `self._db.get()` per row, which was an O(n) SELECT-per-row
        pattern for long-history tickers. See this task's `decisions` entry.

        `existing_by_date` is kept in sync as rows are added within the loop
        (not just pre-populated from the DB before it), so a `frame` that
        itself contains two rows for the same normalized date -- a malformed
        or duplicate source response -- updates the same just-added row
        instead of attempting a second INSERT with an identical composite PK.
        This restores the self-healing behavior the old per-row
        `self._db.get()` lookup got for free from SQLAlchemy's identity map,
        which the bulk-dict rewrite above had otherwise dropped. See this
        task's `decisions` entry.
        """
        fetched_at = _utcnow()
        # Deliberately re-runs the same query `_get`'s `cached_rows` already
        # ran, rather than reusing that earlier snapshot -- this is a known,
        # accepted trade-off, not an oversight. `cached_rows` was read
        # *before* the network fetch in `_get`; re-querying here, right
        # before the upsert, picks up any rows a concurrent request managed
        # to commit during that fetch, narrowing (not just duplicating) the
        # race window the `except (IntegrityError, OperationalError)` below
        # exists for. Reusing `cached_rows` would save one cheap local SQLite
        # SELECT per cache-miss/stale-refresh call, at the cost of widening
        # that race window back out to cover the full fetch duration. See
        # this task's `decisions` entry.
        existing_by_date = {row.date: row for row in self._read_cache(ticker, interval)}
        for idx, row in frame.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else idx
            existing = existing_by_date.get(bar_date)
            if existing is None:
                existing = OHLCVCacheORM(ticker=ticker, date=bar_date, interval=interval)
                self._db.add(existing)
                existing_by_date[bar_date] = existing
            existing.open = float(row["open"])
            existing.high = float(row["high"])
            existing.low = float(row["low"])
            existing.close = float(row["close"])
            existing.volume = float(row["volume"])
            existing.fetched_at = fetched_at
        try:
            self._db.commit()
        except (IntegrityError, OperationalError):
            # Two concurrent first-time-population calls for the same
            # (ticker, interval) can both see no existing row for a given date
            # above and both try to insert it, so the loser's commit hits the
            # composite primary key (IntegrityError). SQLite's default
            # file-level write locking -- no WAL mode or explicit
            # `busy_timeout` configured on the engine (app/db/session.py) --
            # also makes a genuinely concurrent commit at least as likely to
            # instead raise OperationalError ("database is locked"),
            # depending on timing, so both are caught the same way here.
            # Rather than a locking mechanism, the loser just discards its
            # own attempted write: the winner's equivalent, concurrently-
            # committed rows are already (or about to be) in the cache, and
            # `_get` returns `frame` (the data this call itself just fetched)
            # to its caller regardless of whether this upsert's commit
            # succeeds -- so no caller-visible data is lost, only a wasted
            # write. See this task's `decisions` entry.
            #
            # This except is scoped to the whole commit rather than only the
            # composite-PK conflict it's documented/tested for, because
            # SQLAlchemy/SQLite don't offer a cheap, portable way to inspect
            # *which* constraint an IntegrityError came from without parsing
            # driver-specific message text (`orig`) -- fragile across SQLite
            # versions and not worth it for the one constraint OHLCVCacheORM
            # currently has. Verified against the current schema (app/db/
            # models.py) that the composite PK is the only NOT NULL/UNIQUE/FK
            # constraint on this table today, so this can't currently mask an
            # unrelated integrity bug. Revisit (narrow the catch, or inspect
            # `orig`) if OHLCVCacheORM ever gains another constraint.
            self._db.rollback()
            logger.warning(
                "Concurrent cache population for %r (%s) raced this upsert; discarding "
                "this attempt in favor of the concurrently-committed rows.",
                ticker,
                interval,
            )

    @staticmethod
    def _rows_to_frame(rows: list[OHLCVCacheORM]) -> pd.DataFrame:
        df = pd.DataFrame(
            {column: [getattr(r, column) for r in rows] for column in _COLUMNS},
            index=pd.DatetimeIndex([r.date for r in rows], name="date"),
        )
        return df
