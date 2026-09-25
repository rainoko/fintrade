"""Integration tests for the (ticker, range)-keyed IndicatorHistoryResponse cache
(app/api/indicator_history_cache.py) added by backend-indicator-history-performance --
cache hit, cache miss, and TTL expiry against GET /api/stocks/{ticker}/indicators.

Unit-level coverage of `IndicatorHistoryResponseCache` itself (in isolation from the router
and provider) lives in tests/unit/api/test_indicator_history_cache.py; these tests instead
confirm the router actually wires the cache in -- a cache hit skips the provider entirely, a
miss populates it, and a stale (yesterday's) row is treated as a miss.
"""

from datetime import timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_provider
from app.data.base import ExtendedData
from app.db.models import Base, IndicatorHistoryCacheORM
from app.db.session import get_db
from app.main import app
from app.signals.timeframe import TradingMode
from app.time_utils import utcnow
from app.trading_mode import set_trading_mode_setting

_EMPTY_EXTENDED_DATA = ExtendedData(
    earnings_date=None,
    ex_dividend_date=None,
    shares_short=None,
    short_ratio=None,
    short_percent_of_float=None,
    float_shares=None,
    insider_transactions=[],
)


class _CountingStubProvider:
    """A minimal DataProvider stand-in that records how many times each method is called --
    the whole point of the response cache is that a cache hit calls the provider zero times."""

    def __init__(self, daily: pd.DataFrame, weekly: pd.DataFrame) -> None:
        self._daily = daily
        self._weekly = weekly
        self.daily_calls = 0
        self.weekly_calls = 0

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        self.daily_calls += 1
        return self._daily

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        self.weekly_calls += 1
        return self._weekly

    def get_extended_data(self, ticker: str) -> ExtendedData:
        return _EMPTY_EXTENDED_DATA


def _hold_daily_ohlcv(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="D", name="date"),
    )


def _hold_weekly_ohlcv(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000_000] * n,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="W", name="date"),
    )


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _get_indicator_history(client: TestClient, provider, ticker: str = "AAPL", **params):
    app.dependency_overrides[get_data_provider] = lambda: provider
    try:
        return client.get(f"/api/stocks/{ticker}/indicators", params=params)
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


class TestIndicatorHistoryResponseCacheWiring:
    def test_cache_miss_calls_provider_and_populates_cache(
        self, client: TestClient, db_session: Session
    ) -> None:
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        response = _get_indicator_history(client, provider, range="1y")

        assert response.status_code == 200
        assert provider.daily_calls == 1
        assert provider.weekly_calls == 1
        row = (
            db_session.query(IndicatorHistoryCacheORM)
            .filter(
                IndicatorHistoryCacheORM.ticker == "AAPL",
                IndicatorHistoryCacheORM.range == "1y",
            )
            .one()
        )
        assert row.response_json  # a non-empty serialized response was stored

    def test_cache_hit_never_calls_provider_and_returns_identical_body(
        self, client: TestClient
    ) -> None:
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        first = _get_indicator_history(client, provider, range="1y")
        assert first.status_code == 200
        assert provider.daily_calls == 1
        assert provider.weekly_calls == 1

        # A second request for the same (ticker, range) must be served entirely from the
        # cache -- the provider is never called again, even though this second call passes a
        # provider that would raise if it *were* called.
        class _ExplodingProvider:
            def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise AssertionError("cache hit should never call get_daily_ohlcv")

            def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise AssertionError("cache hit should never call get_weekly_ohlcv")

            def get_extended_data(self, ticker: str) -> ExtendedData:
                return _EMPTY_EXTENDED_DATA

        second = _get_indicator_history(client, _ExplodingProvider(), range="1y")

        assert second.status_code == 200
        assert second.json() == first.json()

    def test_cache_hit_still_echoes_a_trading_mode_change_made_after_it_was_cached(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A cached response's `trading_mode` field must never be served stale: if the global
        setting changes after the response was cached (but the request still lands in this
        swing-cache branch -- day_trader with no configured triple is treated the same as
        swing, per `get_indicator_history`'s own docstring), the field on a cache hit must
        reflect the freshly-resolved setting, not whatever was baked into the payload at
        write time. A non-discriminating version of this fix (returning `cached_response`
        as-is) would make this test fail with `trading_mode.mode == "swing"`."""
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        first = _get_indicator_history(client, provider, range="1y")
        assert first.status_code == 200
        assert first.json()["trading_mode"]["mode"] == "swing"
        assert provider.daily_calls == 1

        # Switch the global mode to day_trader with no triple configured -- still routed
        # through this same swing-cache branch (see get_indicator_history's own docstring),
        # so this is a genuine cache-hit case, not the separate day-trader-mode branch that
        # never touches this cache at all.
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=None
        )

        class _ExplodingProvider:
            def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise AssertionError("cache hit should never call get_daily_ohlcv")

            def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise AssertionError("cache hit should never call get_weekly_ohlcv")

            def get_extended_data(self, ticker: str) -> ExtendedData:
                return _EMPTY_EXTENDED_DATA

        second = _get_indicator_history(client, _ExplodingProvider(), range="1y")

        assert second.status_code == 200
        assert second.json()["trading_mode"]["mode"] == "day_trader"
        # Every other field of the response is still served straight from the cache
        # (the provider was never called, per _ExplodingProvider above).
        second_sans_mode = {**second.json(), "trading_mode": None}
        first_sans_mode = {**first.json(), "trading_mode": None}
        assert second_sans_mode == first_sans_mode

    def test_different_range_is_a_separate_cache_key(self, client: TestClient) -> None:
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        _get_indicator_history(client, provider, range="1y")
        _get_indicator_history(client, provider, range="max")

        assert provider.daily_calls == 2
        assert provider.weekly_calls == 2

    def test_different_ticker_is_a_separate_cache_key(self, client: TestClient) -> None:
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        _get_indicator_history(client, provider, ticker="AAPL", range="1y")
        _get_indicator_history(client, provider, ticker="MSFT", range="1y")

        assert provider.daily_calls == 2
        assert provider.weekly_calls == 2

    def test_stale_cache_entry_from_a_prior_day_is_a_miss(
        self, client: TestClient, db_session: Session
    ) -> None:
        provider = _CountingStubProvider(_hold_daily_ohlcv(), _hold_weekly_ohlcv())

        first = _get_indicator_history(client, provider, range="1y")
        assert first.status_code == 200
        assert provider.daily_calls == 1

        # Back-date the cache row's fetched_at to yesterday, simulating a still-present row
        # that's aged out of the same-calendar-day TTL.
        row = (
            db_session.query(IndicatorHistoryCacheORM)
            .filter(
                IndicatorHistoryCacheORM.ticker == "AAPL",
                IndicatorHistoryCacheORM.range == "1y",
            )
            .one()
        )
        row.fetched_at = utcnow() - timedelta(days=1)
        db_session.commit()

        second = _get_indicator_history(client, provider, range="1y")

        assert second.status_code == 200
        assert provider.daily_calls == 2
        assert provider.weekly_calls == 2
