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

from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.data.base import DataProvider
from app.data.exceptions import DataProviderUnavailableError
from app.db.models import OHLCVCacheORM

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
        try:
            return self._call(self._primary, ticker, interval)
        except DataProviderUnavailableError:
            pass

        try:
            return self._call(self._fallback, ticker, interval)
        except DataProviderUnavailableError as exc:
            raise DataProviderUnavailableError(
                f"Both primary and fallback providers failed for {ticker!r} ({interval})"
            ) from exc

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
        """
        fetched_at = _utcnow()
        for idx, row in frame.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else idx
            existing = self._db.get(OHLCVCacheORM, (ticker, bar_date, interval))
            if existing is None:
                existing = OHLCVCacheORM(ticker=ticker, date=bar_date, interval=interval)
                self._db.add(existing)
            existing.open = float(row["open"])
            existing.high = float(row["high"])
            existing.low = float(row["low"])
            existing.close = float(row["close"])
            existing.volume = float(row["volume"])
            existing.fetched_at = fetched_at
        self._db.commit()

    @staticmethod
    def _rows_to_frame(rows: list[OHLCVCacheORM]) -> pd.DataFrame:
        df = pd.DataFrame(
            {column: [getattr(r, column) for r in rows] for column in _COLUMNS},
            index=pd.DatetimeIndex([r.date for r in rows], name="date"),
        )
        return df
