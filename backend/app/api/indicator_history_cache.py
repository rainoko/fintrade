"""Same-calendar-day-TTL cache for the computed `IndicatorHistoryResponse`
(`GET /api/stocks/{ticker}/indicators`, `app/api/routers/stocks.py`) --
docs/tasks/backend-indicator-history-performance.json.

Analogous to `app.data.cache.CachedDataProvider`'s `ohlcv_cache`/`extended_data_cache`
read-through tables, but one layer higher: this caches the *fully computed* response
(the whole per-bar Triple Screen recompute, `app.signals.engine.analyse_history`), not
just the raw OHLCV a `DataProvider` returns. Keyed by `(ticker, range)`
(`IndicatorHistoryCacheORM`, app/db/models.py) since two different `range` values for
the same ticker produce two different `points` lists.

Freshness is judged by *calendar day*, not a rolling `timedelta` window like
`CachedDataProvider._CACHE_TTL` -- see this task's `decisions` entry for why: the
response is a pure function of "daily/weekly OHLCV as of today," so it's valid for the
rest of whatever UTC calendar day it was computed on, and goes stale exactly at the
next day boundary rather than N hours after the specific fetch time.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api.schemas import IndicatorHistoryResponse
from app.db.models import IndicatorHistoryCacheORM
from app.time_utils import today, utcnow

logger = logging.getLogger(__name__)


class IndicatorHistoryResponseCache:
    """Read-through cache for one `(ticker, range)`-keyed `IndicatorHistoryResponse`."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, ticker: str, range_: str) -> IndicatorHistoryResponse | None:
        """The cached response for `(ticker, range_)` if one exists and was computed
        earlier today (UTC) -- `None` on a cache miss or TTL expiry, in which case the
        caller is expected to compute a fresh response and pass it to `set`."""
        row = self._read(ticker, range_)
        if row is None or not self._is_fresh(row):
            return None
        return IndicatorHistoryResponse.model_validate_json(row.response_json)

    def set(self, ticker: str, range_: str, response: IndicatorHistoryResponse) -> None:
        """Insert or update the cached row for `(ticker, range_)` with a freshly
        computed `response`, stamped with the current time."""
        row = self._read(ticker, range_)
        if row is None:
            row = IndicatorHistoryCacheORM(ticker=ticker, range=range_)
            self._db.add(row)
        row.response_json = response.model_dump_json()
        row.fetched_at = utcnow()
        try:
            self._db.commit()
        except (IntegrityError, OperationalError) as exc:
            # Same benign concurrent-first-population race `CachedDataProvider._upsert`'s
            # own except block documents at length: two concurrent cache-miss requests for
            # the same never-yet-cached (ticker, range) can both attempt to insert this row;
            # the loser discards its own write rather than erroring, since `response` (this
            # call's own freshly computed result) is still returned to its caller by
            # `get_indicator_history` regardless of whether this commit succeeds.
            self._db.rollback()
            logger.warning(
                "Concurrent indicator-history cache population for %r (%s) raced this "
                "upsert; discarding this attempt in favor of the concurrently-committed "
                "row. (%s: %s)",
                ticker,
                range_,
                type(exc).__name__,
                exc,
            )

    def _read(self, ticker: str, range_: str) -> IndicatorHistoryCacheORM | None:
        return (
            self._db.query(IndicatorHistoryCacheORM)
            .filter(
                IndicatorHistoryCacheORM.ticker == ticker,
                IndicatorHistoryCacheORM.range == range_,
            )
            .one_or_none()
        )

    @staticmethod
    def _is_fresh(row: IndicatorHistoryCacheORM) -> bool:
        return row.fetched_at.date() == today()
