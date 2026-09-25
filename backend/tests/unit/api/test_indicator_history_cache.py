"""Tests for IndicatorHistoryResponseCache (app/api/indicator_history_cache.py) -- the
same-calendar-day-TTL cache for GET /api/stocks/{ticker}/indicators' computed response
(docs/tasks/backend-indicator-history-performance.json).

Exercises the cache class directly against an in-memory SQLite session (no FastAPI/HTTP layer
involved) -- integration-level "the router actually wires this in" coverage lives in
tests/integration/test_stocks_indicator_history_cache.py.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.indicator_history_cache import IndicatorHistoryResponseCache
from app.api.schemas import (
    IndicatorHistoryPoint,
    IndicatorHistoryResponse,
    TideScreen,
    TradingModeOut,
    TrendStrength,
)
from app.db.models import Base, IndicatorHistoryCacheORM
from app.time_utils import utcnow


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _response(ticker: str = "AAPL") -> IndicatorHistoryResponse:
    return IndicatorHistoryResponse(
        ticker=ticker,
        trading_mode=TradingModeOut(mode="swing", day_trader_timeframe_triple=None),
        points=[
            IndicatorHistoryPoint(
                date="2026-01-01",
                tide=TideScreen(trend="BULLISH", weekly_macd_histogram_slope="rising"),
                ema_13=100.0,
                ema_26=99.0,
                macd_histogram=0.5,
                bull_power=1.0,
                bear_power=-1.0,
                stochastic_k=50.0,
                force_index_2ema=10.0,
                channel_upper=None,
                channel_lower=None,
                rsi=55.0,
                season="Spring",
                trend_strength=TrendStrength(atr=1.0, plus_di=20.0, minus_di=15.0, adx=25.0),
                signal="BUY",
                confidence=80,
                confidence_band="High",
                divergence=None,
                kangaroo_tail=None,
                obv=1000.0,
                accumulation_distribution=500.0,
            )
        ],
    )


class TestGet:
    def test_returns_none_on_a_cache_miss(self, db_session: Session) -> None:
        cache = IndicatorHistoryResponseCache(db_session)

        assert cache.get("AAPL", "1y") is None

    def test_returns_the_cached_response_on_a_fresh_hit(self, db_session: Session) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        response = _response()
        cache.set("AAPL", "1y", response)

        cached = cache.get("AAPL", "1y")

        assert cached is not None
        assert cached == response

    def test_returns_none_for_a_different_range_even_if_the_ticker_is_cached(
        self, db_session: Session
    ) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        cache.set("AAPL", "1y", _response())

        assert cache.get("AAPL", "max") is None

    def test_returns_none_for_a_different_ticker_even_if_the_range_is_cached(
        self, db_session: Session
    ) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        cache.set("AAPL", "1y", _response("AAPL"))

        assert cache.get("MSFT", "1y") is None

    def test_stale_row_from_a_prior_day_is_treated_as_a_miss(self, db_session: Session) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        cache.set("AAPL", "1y", _response())
        row = db_session.query(IndicatorHistoryCacheORM).one()
        row.fetched_at = utcnow() - timedelta(days=1)
        db_session.commit()

        assert cache.get("AAPL", "1y") is None

    def test_row_from_earlier_the_same_day_is_still_fresh(self, db_session: Session) -> None:
        """The TTL is "same calendar day", not a rolling window -- a row fetched many hours
        ago earlier today is still fresh as long as the calendar day hasn't turned over,
        unlike CachedDataProvider's rolling 24h `_CACHE_TTL` (see this task's `decisions`
        entry)."""
        cache = IndicatorHistoryResponseCache(db_session)
        cache.set("AAPL", "1y", _response())
        row = db_session.query(IndicatorHistoryCacheORM).one()
        row.fetched_at = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        db_session.commit()

        assert cache.get("AAPL", "1y") is not None


class TestSet:
    def test_overwrites_an_existing_row_for_the_same_key(self, db_session: Session) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        cache.set("AAPL", "1y", _response("AAPL"))
        updated = _response("AAPL")
        updated.points[0].confidence = 42

        cache.set("AAPL", "1y", updated)

        assert db_session.query(IndicatorHistoryCacheORM).count() == 1
        cached = cache.get("AAPL", "1y")
        assert cached is not None
        assert cached.points[0].confidence == 42

    def test_distinct_keys_get_distinct_rows(self, db_session: Session) -> None:
        cache = IndicatorHistoryResponseCache(db_session)

        cache.set("AAPL", "1y", _response("AAPL"))
        cache.set("AAPL", "max", _response("AAPL"))
        cache.set("MSFT", "1y", _response("MSFT"))

        assert db_session.query(IndicatorHistoryCacheORM).count() == 3


class TestConcurrentFirstPopulation:
    """Same benign concurrent-first-population race CachedDataProvider's own
    TestConcurrentFirstPopulation (tests/unit/data/test_cache.py) covers: two concurrent
    cache-miss requests for the same never-yet-cached (ticker, range) can both attempt to
    insert this row, so one commit fails -- `set` should swallow that (log, not raise) rather
    than propagate an unhandled 500, since the caller already has the freshly computed
    response to return regardless of whether this write itself lands."""

    def test_integrity_error_on_set_commit_is_swallowed_not_raised(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        original_commit = db_session.commit

        def _commit_raises_once():
            monkeypatch.setattr(db_session, "commit", original_commit)
            db_session.rollback()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_once)

        cache.set("AAPL", "1y", _response())  # must not raise

        # the swallowed commit means the row never actually landed in this session's view of
        # the cache -- the accepted trade-off, same as CachedDataProvider's own equivalent race
        assert db_session.query(IndicatorHistoryCacheORM).count() == 0

    def test_operational_error_on_set_commit_is_also_swallowed_not_raised(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = IndicatorHistoryResponseCache(db_session)
        original_commit = db_session.commit

        def _commit_raises_once():
            monkeypatch.setattr(db_session, "commit", original_commit)
            db_session.rollback()
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_once)

        cache.set("AAPL", "1y", _response())  # must not raise

        assert db_session.query(IndicatorHistoryCacheORM).count() == 0
