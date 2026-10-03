"""DB-backed read-through + scheduled-refresh cache in front of `CFTCCOTProvider`
(docs/tasks/backend-cftc-cot-caching-scheduler.json), fulfilling the follow-up
`backend-cftc-cot-data`'s own `decisions` entry explicitly pre-approved: "adding a
caching layer (e.g. a new ORM table keyed by market+report_date, mirroring
`IBKRBreadthSnapshotORM`) is a reasonable follow-up if this endpoint turns out to be
called often enough that repeated CFTC round-trips matter".

Unlike `app.data.cache.CachedDataProvider` (a lazy, pull-based, per-ticker TTL cache),
this is a push-based cache: the CFTC only publishes new data once a week, so staleness
is judged -- and a refresh triggered -- by a scheduled background loop
(`app.main._cftc_cot_refresh_loop`), not by a TTL check on every read. `GET
/api/cftc/cot` (`app.api.routers.cftc`) only ever falls back to a live fetch on a
genuine cache miss (an empty cache, e.g. before the scheduled loop's first run) -- see
this task's `decisions` entry for why a per-request staleness check was deliberately
*not* added on top of that, unlike every other cache in this codebase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.data.cftc_cot_provider import COT_MARKETS, COTWeeklyReport
from app.db.models import CFTCCOTCacheORM
from app.time_utils import utcnow

logger = logging.getLogger(__name__)


class CFTCCOTCache:
    """Read-through cache for `CFTCCOTProvider.get_all_recent()`'s per-market report
    lists, backed by `CFTCCOTCacheORM`."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_cached_reports(self) -> dict[str, list[COTWeeklyReport]] | None:
        """All cached reports, most-recent-first per market (matching
        `CFTCCOTProvider.get_all_recent`'s own contract) -- or `None` on a genuine cache
        miss: at least one of `COT_MARKETS`' fixed keys has no cached row at all (e.g.
        before the scheduled refresh loop has ever run). A market with *some* rows but
        fewer than `app.data.cftc_cot_provider.WEEKS_OF_HISTORY` is NOT a miss -- that's
        just how much history has been persisted so far, exactly like a freshly-fetched
        live response can also have fewer than `WEEKS_OF_HISTORY` rows if the CFTC's own
        published history for that contract doesn't go back that far.

        Deliberately does not consider *staleness* here (how long ago the newest row was
        fetched) -- see this module's own docstring and this task's `decisions` entry for
        why that check belongs solely to the scheduled background loop, not this read
        path.
        """
        rows = self._db.query(CFTCCOTCacheORM).order_by(CFTCCOTCacheORM.report_date.desc()).all()
        by_market: dict[str, list[COTWeeklyReport]] = {}
        for row in rows:
            by_market.setdefault(row.market_key, []).append(_row_to_report(row))

        if any(not by_market.get(market_key) for market_key in COT_MARKETS):
            return None
        return by_market

    def most_recent_fetch(self) -> datetime | None:
        """The newest `fetched_at` across every cached row, or `None` if the cache is
        entirely empty -- used by `app.main._cftc_cot_refresh_loop` to judge staleness.
        Deliberately the max across *all* rows (not per-market): `refresh` always writes
        every market in the same call with the same `fetched_at` stamp (`CFTCCOTProvider.
        get_all_recent` fetches every market in one request), so in practice every row
        this cache ever writes shares the same `fetched_at` as its siblings from the same
        refresh.
        """
        return self._db.query(func.max(CFTCCOTCacheORM.fetched_at)).scalar()

    def is_stale(self, max_age: timedelta) -> bool:
        """Whether a refresh is due: the cache is empty, or its newest fetch is older
        than `max_age`."""
        most_recent = self.most_recent_fetch()
        if most_recent is None:
            return True
        return utcnow() - most_recent >= max_age

    def refresh(self, reports_by_market: dict[str, list[COTWeeklyReport]]) -> None:
        """Insert/update every row in `reports_by_market` (as fetched fresh from
        `CFTCCOTProvider.get_all_recent()`) and prune any existing row for a market that
        fell outside this fetch's own window -- see `CFTCCOTCacheORM`'s own docstring for
        why this table is actively pruned rather than left to grow forever.

        Commits once per market (PR #380 review, round 3's non-blocking finding) rather
        than once for the whole multi-market batch -- matching `CachedDataProvider._upsert`
        /`_upsert_extended` (app/data/cache.py)'s own per-entity (there, per-ticker)
        granularity. A single-commit-per-batch shape meant a PK-collision race on any one
        market's row (the scheduled loop racing a concurrent on-demand cache-miss fetch,
        `test_integrity_error_on_commit_is_swallowed_not_raised`'s own scenario) discarded
        every other market's successfully-fetched writes too, not just the colliding row --
        wasteful, not incorrect (the rollback+log-never-raise race-safety behavior was
        always intact), but it forced an unnecessarily early full re-fetch of markets that
        never actually raced anything. Per-market commits narrow that discarded blast
        radius to just the one market that actually collided.
        """
        fetched_at = utcnow()
        for market_key, reports in reports_by_market.items():
            existing_by_date = {
                row.report_date: row
                for row in self._db.query(CFTCCOTCacheORM)
                .filter(CFTCCOTCacheORM.market_key == market_key)
                .all()
            }
            fresh_dates = {report.report_date for report in reports}
            for report in reports:
                row = existing_by_date.get(report.report_date)
                if row is None:
                    row = CFTCCOTCacheORM(market_key=market_key, report_date=report.report_date)
                    self._db.add(row)
                    existing_by_date[report.report_date] = row
                row.display_name = report.market_and_exchange_name
                row.open_interest = report.open_interest
                row.commercial_long = report.commercial_long
                row.commercial_short = report.commercial_short
                row.large_speculator_long = report.large_speculator_long
                row.large_speculator_short = report.large_speculator_short
                row.small_speculator_long = report.small_speculator_long
                row.small_speculator_short = report.small_speculator_short
                row.fetched_at = fetched_at
            for report_date, row in existing_by_date.items():
                if report_date not in fresh_dates:
                    self._db.delete(row)

            try:
                self._db.commit()
            except (IntegrityError, OperationalError) as exc:
                # Same benign concurrent-first-population race `CachedDataProvider._upsert`
                # (app/data/cache.py) and `IndicatorHistoryResponseCache.set` document at
                # length: two concurrent cache-miss callers (an on-demand `GET /api/cftc/cot`
                # racing the scheduled refresh loop, or two concurrent requests both hitting
                # a cold cache) can both attempt to insert the same (market_key, report_date)
                # row; the loser discards its own write for *this market only* rather than
                # erroring, since `reports_by_market` (this call's own freshly fetched
                # result) is still usable by its caller regardless of whether this commit
                # succeeds, and the loop continues on to commit the remaining markets'
                # writes independently.
                self._db.rollback()
                logger.warning(
                    "Concurrent CFTC COT cache population raced this upsert for market %r; "
                    "discarding this market's attempt in favor of the concurrently-committed "
                    "rows. (%s: %s)",
                    market_key,
                    type(exc).__name__,
                    exc,
                )


def _row_to_report(row: CFTCCOTCacheORM) -> COTWeeklyReport:
    return COTWeeklyReport(
        report_date=row.report_date,
        market_and_exchange_name=row.display_name,
        open_interest=row.open_interest,
        commercial_long=row.commercial_long,
        commercial_short=row.commercial_short,
        large_speculator_long=row.large_speculator_long,
        large_speculator_short=row.large_speculator_short,
        small_speculator_long=row.small_speculator_long,
        small_speculator_short=row.small_speculator_short,
    )
