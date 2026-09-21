"""Naive-UTC "now"/"today" helpers shared by every module that stores or compares timestamps
against this codebase's naive-UTC datetime/date columns (`OHLCVCacheORM.fetched_at`,
`ExtendedDataCacheORM.fetched_at`, `WatchlistItemORM.added_at`, `ClosedTradeORM.exit_date`,
`DailyHomeworkEntryORM.date`/`recorded_at`) -- consolidated here (per PR #216's review
follow-up, docs/tasks/backend-daily-homework-self-test-followups.json) rather than
copy-pasted into `app/data/cache.py` and each of `app/api/routers/{portfolio,watchlist,
homework}.py`, which had each defined an identical private `_utcnow`/`_today` pair.
"""

from datetime import UTC, date, datetime


def utcnow() -> datetime:
    """Naive UTC 'now' (tzinfo stripped after conversion), matching how every naive-UTC
    datetime column in this codebase is stored/compared."""
    return datetime.now(UTC).replace(tzinfo=None)


def today() -> date:
    """Naive UTC 'today', matching how every naive-UTC date column in this codebase is
    stored/compared."""
    return datetime.now(UTC).date()
