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
from sqlalchemy.orm import Session, sessionmaker

from app.data.cache import CachedDataProvider
from app.data.exceptions import DataProviderUnavailableError, TickerNotFoundError
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
