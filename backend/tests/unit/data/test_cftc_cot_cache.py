"""Tests for CFTCCOTCache (app/data/cftc_cot_cache.py) -- the DB-backed read-through +
scheduled-refresh cache in front of CFTCCOTProvider
(docs/tasks/backend-cftc-cot-caching-scheduler.json).

An in-memory SQLite `Session` per test (matching tests/unit/data/test_cache.py's own
`session` fixture) -- nothing here makes a live network call, per
docs/architecture/Testing.md.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.data.cftc_cot_cache import CFTCCOTCache
from app.data.cftc_cot_provider import COT_MARKETS, COTWeeklyReport
from app.db.models import Base, CFTCCOTCacheORM
from app.time_utils import utcnow


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _report(
    *,
    report_date: str,
    name: str = "GOLD - COMMODITY EXCHANGE INC.",
    open_interest: int = 100_000,
    comm_long: int = 40_000,
    comm_short: int = 30_000,
    noncomm_long: int = 35_000,
    noncomm_short: int = 45_000,
    nonrept_long: int = 10_000,
    nonrept_short: int = 12_000,
) -> COTWeeklyReport:
    return COTWeeklyReport(
        report_date=date.fromisoformat(report_date),
        market_and_exchange_name=name,
        open_interest=open_interest,
        commercial_long=comm_long,
        commercial_short=comm_short,
        large_speculator_long=noncomm_long,
        large_speculator_short=noncomm_short,
        small_speculator_long=nonrept_long,
        small_speculator_short=nonrept_short,
    )


def _all_markets_reports(dates: list[str]) -> dict[str, list[COTWeeklyReport]]:
    """One report per `dates` entry, for every `COT_MARKETS` key -- `dates` most-recent-
    first, matching `CFTCCOTProvider.get_all_recent`'s own contract."""
    return {key: [_report(report_date=d, name=f"NAME-{key}") for d in dates] for key in COT_MARKETS}


class TestGetCachedReports:
    def test_empty_cache_is_a_genuine_miss(self, session: Session) -> None:
        assert CFTCCOTCache(session).get_cached_reports() is None

    def test_all_markets_populated_returns_most_recent_first_per_market(self, session: Session) -> None:
        cache = CFTCCOTCache(session)
        cache.refresh(_all_markets_reports(["2026-09-08", "2026-09-15"]))

        cached = cache.get_cached_reports()

        assert cached is not None
        assert set(cached.keys()) == set(COT_MARKETS.keys())
        gold = cached["gold"]
        assert [r.report_date.isoformat() for r in gold] == ["2026-09-15", "2026-09-08"]
        assert gold[0].market_and_exchange_name == "NAME-gold"
        assert gold[0].commercial_long == 40_000
        assert gold[0].commercial_net == 10_000

    def test_one_market_missing_is_still_a_genuine_miss(self, session: Session) -> None:
        """Even if every *other* market is fully populated, a single missing market
        (e.g. a prior refresh that only partially completed) must still read as a cache
        miss -- `GET /api/cftc/cot` needs all 5 fixed markets to build its response."""
        reports = _all_markets_reports(["2026-09-15"])
        del reports["bonds"]
        cache = CFTCCOTCache(session)
        cache.refresh(reports)

        assert cache.get_cached_reports() is None


class TestRefresh:
    def test_inserts_new_rows(self, session: Session) -> None:
        CFTCCOTCache(session).refresh(_all_markets_reports(["2026-09-15"]))

        rows = session.query(CFTCCOTCacheORM).filter_by(market_key="gold").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.report_date == date(2026, 9, 15)
        assert row.display_name == "NAME-gold"
        assert row.open_interest == 100_000
        assert row.commercial_long == 40_000
        assert row.commercial_short == 30_000
        assert row.large_speculator_long == 35_000
        assert row.large_speculator_short == 45_000
        assert row.small_speculator_long == 10_000
        assert row.small_speculator_short == 12_000

    def test_updates_existing_row_for_the_same_report_date_in_place(self, session: Session) -> None:
        cache = CFTCCOTCache(session)
        cache.refresh(_all_markets_reports(["2026-09-15"]))

        updated = {
            "gold": [_report(report_date="2026-09-15", name="NAME-gold", comm_long=99_000)],
        }
        cache.refresh(updated)

        rows = session.query(CFTCCOTCacheORM).filter_by(market_key="gold").all()
        assert len(rows) == 1
        assert rows[0].commercial_long == 99_000

    def test_prunes_rows_that_fall_outside_the_new_fetch_window(self, session: Session) -> None:
        """A market's oldest cached report_date, no longer present in a fresh
        `get_all_recent()` response (the provider's own `WEEKS_OF_HISTORY`-bounded
        window has moved on), is deleted rather than left behind forever -- see
        `CFTCCOTCacheORM`'s own docstring for why this table is actively pruned."""
        cache = CFTCCOTCache(session)
        cache.refresh({"gold": [_report(report_date="2026-09-01", name="NAME-gold")]})
        assert session.query(CFTCCOTCacheORM).filter_by(market_key="gold").count() == 1

        # A later refresh's window no longer includes 2026-09-01.
        cache.refresh({"gold": [_report(report_date="2026-09-15", name="NAME-gold")]})

        rows = session.query(CFTCCOTCacheORM).filter_by(market_key="gold").all()
        assert [r.report_date.isoformat() for r in rows] == ["2026-09-15"]

    def test_does_not_prune_a_market_not_present_in_this_refresh_call(self, session: Session) -> None:
        """`refresh` only prunes rows for markets it was actually given -- a caller that
        refreshes one market at a time (as the unit tests above do) must not have every
        *other* market's cache silently wiped out."""
        cache = CFTCCOTCache(session)
        cache.refresh(_all_markets_reports(["2026-09-15"]))

        cache.refresh({"gold": [_report(report_date="2026-09-22", name="NAME-gold")]})

        assert session.query(CFTCCOTCacheORM).filter_by(market_key="eur").count() == 1
        assert session.query(CFTCCOTCacheORM).filter_by(market_key="gold").count() == 1

    def test_integrity_error_on_commit_is_swallowed_not_raised(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same benign concurrent-first-population race `CachedDataProvider._upsert`'s
        own tests document: two concurrent callers (an on-demand request racing the
        scheduled refresh loop) can both attempt to insert the same (market_key,
        report_date) row -- the loser's commit should be rolled back and swallowed
        (logged, not raised)."""
        cache = CFTCCOTCache(session)
        original_commit = session.commit

        def _commit_raises_once():
            monkeypatch.setattr(session, "commit", original_commit)
            session.rollback()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(session, "commit", _commit_raises_once)

        cache.refresh(_all_markets_reports(["2026-09-15"]))  # must not raise

        assert session.query(CFTCCOTCacheORM).count() == 0

    def test_operational_error_on_commit_is_also_swallowed_not_raised(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = CFTCCOTCache(session)
        original_commit = session.commit

        def _commit_raises_once():
            monkeypatch.setattr(session, "commit", original_commit)
            session.rollback()
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

        monkeypatch.setattr(session, "commit", _commit_raises_once)

        cache.refresh(_all_markets_reports(["2026-09-15"]))  # must not raise

        assert session.query(CFTCCOTCacheORM).count() == 0


class TestStaleness:
    def test_most_recent_fetch_is_none_when_cache_is_empty(self, session: Session) -> None:
        assert CFTCCOTCache(session).most_recent_fetch() is None

    def test_most_recent_fetch_returns_the_stamped_fetched_at(self, session: Session) -> None:
        cache = CFTCCOTCache(session)
        before = utcnow()
        cache.refresh(_all_markets_reports(["2026-09-15"]))
        after = utcnow()

        most_recent = cache.most_recent_fetch()

        assert most_recent is not None
        assert before <= most_recent <= after

    def test_is_stale_true_when_cache_is_empty(self, session: Session) -> None:
        assert CFTCCOTCache(session).is_stale(timedelta(days=6)) is True

    def test_is_stale_false_when_freshly_refreshed(self, session: Session) -> None:
        cache = CFTCCOTCache(session)
        cache.refresh(_all_markets_reports(["2026-09-15"]))

        assert cache.is_stale(timedelta(days=6)) is False

    def test_is_stale_true_once_older_than_max_age(self, session: Session) -> None:
        cache = CFTCCOTCache(session)
        cache.refresh(_all_markets_reports(["2026-09-15"]))
        stale_fetched_at = utcnow() - timedelta(days=10)
        session.query(CFTCCOTCacheORM).update({CFTCCOTCacheORM.fetched_at: stale_fetched_at})
        session.commit()

        assert cache.is_stale(timedelta(days=6)) is True
