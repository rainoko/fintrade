"""Tests for CachedDataProvider (app/data/cache.py) -- the SQLite read-through
cache wrapping a primary + fallback DataProvider (docs/architecture/Backend.md §7).

Providers are lightweight in-process stubs, not the real YFinanceProvider/
StooqProvider, so nothing here ever makes a live network call (this suite's
own "no live network calls" scenario, per this task's checklist).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.data.cache import CachedDataProvider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.db.models import Base, OHLCVCacheORM


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _frame(dates: list[str], closes: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(dates, name="date")
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000.0 for _ in closes],
        },
        index=idx,
    )


class _StubProvider:
    """A minimal DataProvider stand-in that records calls and can be told to
    return a fixed frame or raise a fixed exception per method.
    """

    def __init__(self, *, daily=None, weekly=None, daily_exc=None, weekly_exc=None) -> None:
        self.daily = daily
        self.weekly = weekly
        self.daily_exc = daily_exc
        self.weekly_exc = weekly_exc
        self.daily_calls: list[str] = []
        self.weekly_calls: list[str] = []

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        self.daily_calls.append(ticker)
        if self.daily_exc is not None:
            raise self.daily_exc
        return self.daily

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        self.weekly_calls.append(ticker)
        if self.weekly_exc is not None:
            raise self.weekly_exc
        return self.weekly


@pytest.fixture
def session():
    """A fresh in-memory SQLite database + session per test (matches tests/unit/test_db_models.py)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed(session: Session, *, ticker: str, interval: str, date_: object, close: float, fetched_at: datetime) -> None:
    session.add(
        OHLCVCacheORM(
            ticker=ticker,
            date=date_,
            interval=interval,
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000.0,
            fetched_at=fetched_at,
        )
    )
    session.commit()


class TestFullyCached:
    def test_serves_from_cache_without_calling_source(self, session: Session) -> None:
        _seed(
            session,
            ticker="AAPL",
            interval="daily",
            date_=datetime(2026, 1, 2).date(),
            close=190.0,
            fetched_at=_now(),
        )
        primary = _StubProvider()
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_daily_ohlcv("AAPL")

        assert primary.daily_calls == []
        assert fallback.daily_calls == []
        assert list(result.index.date) == [datetime(2026, 1, 2).date()]
        assert result["close"].iloc[0] == 190.0


class TestPartiallyCached:
    def test_refreshes_stale_cache_and_upserts_new_and_updated_rows(self, session: Session) -> None:
        stale_fetched_at = _now() - timedelta(hours=48)
        _seed(
            session,
            ticker="AAPL",
            interval="daily",
            date_=datetime(2026, 1, 2).date(),
            close=190.0,
            fetched_at=stale_fetched_at,
        )
        fresh = _frame(["2026-01-02", "2026-01-03"], [191.0, 192.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_daily_ohlcv("AAPL")

        assert primary.daily_calls == ["AAPL"]
        assert fallback.daily_calls == []
        assert list(result["close"]) == [191.0, 192.0]

        rows = (
            session.query(OHLCVCacheORM)
            .filter_by(ticker="AAPL", interval="daily")
            .order_by(OHLCVCacheORM.date)
            .all()
        )
        assert len(rows) == 2
        assert rows[0].close == 191.0
        assert rows[0].fetched_at > stale_fetched_at
        assert rows[1].date == datetime(2026, 1, 3).date()


class TestEmptyCache:
    def test_fetches_from_primary_and_populates_cache(self, session: Session) -> None:
        fresh = _frame(["2026-02-01"], [100.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_daily_ohlcv("MSFT")

        assert primary.daily_calls == ["MSFT"]
        assert list(result["close"]) == [100.0]

        rows = session.query(OHLCVCacheORM).filter_by(ticker="MSFT", interval="daily").all()
        assert len(rows) == 1
        assert rows[0].close == 100.0

    def test_get_weekly_ohlcv_is_cached_under_a_distinct_interval(self, session: Session) -> None:
        weekly = _frame(["2026-02-06"], [105.0])
        primary = _StubProvider(weekly=weekly)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_weekly_ohlcv("MSFT")

        assert primary.weekly_calls == ["MSFT"]
        assert list(result["close"]) == [105.0]
        rows = session.query(OHLCVCacheORM).filter_by(ticker="MSFT").all()
        assert [r.interval for r in rows] == ["weekly"]


class TestFallback:
    def test_falls_back_to_secondary_provider_when_primary_is_unavailable(self, session: Session) -> None:
        fresh = _frame(["2026-03-01"], [50.0])
        primary = _StubProvider(daily_exc=DataProviderUnavailableError("yfinance rate-limited"))
        fallback = _StubProvider(daily=fresh)
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_daily_ohlcv("TSLA")

        assert primary.daily_calls == ["TSLA"]
        assert fallback.daily_calls == ["TSLA"]
        assert list(result["close"]) == [50.0]
        rows = session.query(OHLCVCacheORM).filter_by(ticker="TSLA").all()
        assert len(rows) == 1

    def test_ticker_not_found_on_primary_propagates_without_trying_fallback(self, session: Session) -> None:
        primary = _StubProvider(daily_exc=TickerNotFoundError("NOPE"))
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        with pytest.raises(TickerNotFoundError):
            provider.get_daily_ohlcv("NOPE")

        assert primary.daily_calls == ["NOPE"]
        assert fallback.daily_calls == []
        assert session.query(OHLCVCacheORM).count() == 0

    def test_insufficient_history_on_primary_propagates_without_trying_fallback(self, session: Session) -> None:
        primary = _StubProvider(
            daily_exc=InsufficientHistoryError("IPO", available=3, required=130)
        )
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        with pytest.raises(InsufficientHistoryError):
            provider.get_daily_ohlcv("IPO")

        assert primary.daily_calls == ["IPO"]
        assert fallback.daily_calls == []
        assert session.query(OHLCVCacheORM).count() == 0

    def test_falls_back_to_secondary_provider_for_weekly_when_primary_is_unavailable(
        self, session: Session
    ) -> None:
        fresh = _frame(["2026-03-06"], [55.0])
        primary = _StubProvider(weekly_exc=DataProviderUnavailableError("yfinance rate-limited"))
        fallback = _StubProvider(weekly=fresh)
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_weekly_ohlcv("TSLA")

        assert primary.weekly_calls == ["TSLA"]
        assert fallback.weekly_calls == ["TSLA"]
        assert list(result["close"]) == [55.0]
        rows = session.query(OHLCVCacheORM).filter_by(ticker="TSLA", interval="weekly").all()
        assert len(rows) == 1


class TestBothProvidersFailed:
    def test_raises_data_provider_unavailable_when_cache_is_empty(self, session: Session) -> None:
        primary = _StubProvider(daily_exc=DataProviderUnavailableError("yfinance down"))
        fallback = _StubProvider(daily_exc=DataProviderUnavailableError("stooq down"))
        provider = CachedDataProvider(primary, fallback, session)

        with pytest.raises(DataProviderUnavailableError):
            provider.get_daily_ohlcv("AAPL")

        assert primary.daily_calls == ["AAPL"]
        assert fallback.daily_calls == ["AAPL"]
        assert session.query(OHLCVCacheORM).count() == 0

    def test_raises_when_refreshing_a_stale_cache_and_both_providers_fail(self, session: Session) -> None:
        stale_fetched_at = _now() - timedelta(hours=48)
        _seed(
            session,
            ticker="AAPL",
            interval="daily",
            date_=datetime(2026, 1, 2).date(),
            close=190.0,
            fetched_at=stale_fetched_at,
        )
        primary = _StubProvider(daily_exc=DataProviderUnavailableError("yfinance down"))
        fallback = _StubProvider(daily_exc=DataProviderUnavailableError("stooq down"))
        provider = CachedDataProvider(primary, fallback, session)

        with pytest.raises(DataProviderUnavailableError):
            provider.get_daily_ohlcv("AAPL")

        # the pre-existing stale row is untouched -- no partial/failed upsert occurred
        rows = session.query(OHLCVCacheORM).filter_by(ticker="AAPL").all()
        assert len(rows) == 1
        assert rows[0].fetched_at == stale_fetched_at

    def test_raises_data_provider_unavailable_for_weekly_when_cache_is_empty(self, session: Session) -> None:
        primary = _StubProvider(weekly_exc=DataProviderUnavailableError("yfinance down"))
        fallback = _StubProvider(weekly_exc=DataProviderUnavailableError("stooq down"))
        provider = CachedDataProvider(primary, fallback, session)

        with pytest.raises(DataProviderUnavailableError):
            provider.get_weekly_ohlcv("AAPL")

        assert primary.weekly_calls == ["AAPL"]
        assert fallback.weekly_calls == ["AAPL"]
        assert session.query(OHLCVCacheORM).count() == 0


class TestVolumeDtype:
    def test_cache_miss_and_cache_hit_paths_both_return_float_volume(self, session: Session) -> None:
        """Regression test for the int64 (cache-miss)/float64 (cache-hit) volume
        dtype inconsistency flagged on this task -- both paths must agree.
        """
        fresh = pd.DataFrame(
            {
                "open": [99.5],
                "high": [101.0],
                "low": [98.0],
                "close": [100.0],
                "volume": [1_000],  # int, as a real provider frame would return
            },
            index=pd.DatetimeIndex(["2026-04-01"], name="date"),
        )
        assert fresh["volume"].dtype == "int64"
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        miss_result = provider.get_daily_ohlcv("AAPL")
        assert miss_result["volume"].dtype == "float64"

        hit_result = provider.get_daily_ohlcv("AAPL")
        assert primary.daily_calls == ["AAPL"]  # only the first call hit the source
        assert hit_result["volume"].dtype == "float64"


class TestUpsertBulkLookup:
    def test_upsert_updates_existing_rows_without_a_per_row_db_get(self, session: Session) -> None:
        """_upsert should reuse a single bulk query rather than `self._db.get()`
        per row -- verified behaviorally (correct insert + update in one pass)
        rather than by mocking internals, since the O(n) fix is an implementation
        detail the public behavior must still match exactly.
        """
        _seed(
            session,
            ticker="AAPL",
            interval="daily",
            date_=datetime(2026, 5, 1).date(),
            close=10.0,
            fetched_at=_now() - timedelta(hours=48),
        )
        fresh = _frame(["2026-05-01", "2026-05-02", "2026-05-03"], [11.0, 12.0, 13.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        provider.get_daily_ohlcv("AAPL")

        rows = (
            session.query(OHLCVCacheORM)
            .filter_by(ticker="AAPL", interval="daily")
            .order_by(OHLCVCacheORM.date)
            .all()
        )
        assert [r.close for r in rows] == [11.0, 12.0, 13.0]


class TestConcurrentFirstPopulation:
    def test_integrity_error_on_upsert_commit_is_swallowed_not_raised(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates the race this task's checklist flags: two concurrent
        first-time-population calls both see no existing row and both try to
        insert it, so one commit raises IntegrityError. `_upsert` should roll
        back and swallow it (logging, not raising) rather than propagate an
        unhandled 500 -- the caller already has the freshly-fetched `frame` to
        return regardless of whether the cache write itself lands.
        """
        fresh = _frame(["2026-06-01"], [20.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        original_commit = session.commit

        def _commit_raises_once():
            monkeypatch.setattr(session, "commit", original_commit)
            session.rollback()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(session, "commit", _commit_raises_once)

        result = provider.get_daily_ohlcv("AAPL")

        assert list(result["close"]) == [20.0]
        # the swallowed commit means the row never actually landed in this
        # session's view of the cache -- that's the accepted trade-off (see
        # this task's `decisions` entry), the caller-visible result is correct
        assert session.query(OHLCVCacheORM).filter_by(ticker="AAPL").count() == 0

    def test_operational_error_on_upsert_commit_is_also_swallowed_not_raised(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same race as above, but SQLite raises OperationalError ("database is
        locked") instead of IntegrityError -- at least as likely an outcome as
        IntegrityError under SQLite's default file-level locking, per this
        task's checklist. `_upsert` must swallow this the same way, not just
        IntegrityError, or the same race has an uncaught outcome depending on
        timing luck.
        """
        fresh = _frame(["2026-06-02"], [21.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        original_commit = session.commit

        def _commit_raises_once():
            monkeypatch.setattr(session, "commit", original_commit)
            session.rollback()
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

        monkeypatch.setattr(session, "commit", _commit_raises_once)

        result = provider.get_daily_ohlcv("AAPL")

        assert list(result["close"]) == [21.0]
        assert session.query(OHLCVCacheORM).filter_by(ticker="AAPL").count() == 0


class TestUpsertDuplicateDateWithinFrame:
    def test_two_rows_for_the_same_date_in_one_frame_are_deduped_not_raised(
        self, session: Session
    ) -> None:
        """Regression test for the identity-map-self-healing regression flagged
        on this task: a fetched frame with two rows sharing one date must not
        raise IntegrityError on commit, and the second (last) occurrence should
        win -- matching what the old per-row `self._db.get()` lookup did via
        SQLAlchemy's identity map before the bulk-dict rewrite.
        """
        fresh = _frame(["2026-07-01", "2026-07-01"], [30.0, 31.0])
        primary = _StubProvider(daily=fresh)
        fallback = _StubProvider()
        provider = CachedDataProvider(primary, fallback, session)

        result = provider.get_daily_ohlcv("DUPE")

        assert list(result["close"]) == [30.0, 31.0]
        rows = session.query(OHLCVCacheORM).filter_by(ticker="DUPE", interval="daily").all()
        assert len(rows) == 1
        assert rows[0].close == 31.0
