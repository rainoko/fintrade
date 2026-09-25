"""Integration tests for GET/POST/DELETE /api/watchlist (app/api/routers/watchlist.py).

Uses an isolated in-memory SQLite session (via a `get_db` dependency override) and a stub
`DataProvider` (via a `get_data_provider` dependency override), matching the pattern in
tests/integration/test_portfolio_get.py, so these tests never touch the real fintrade.db file
or a live market data provider.

The `db_session` fixture lives in tests/integration/conftest.py; this module keeps its own
`client` fixture because it additionally needs the `get_data_provider` override below.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.ibkr_provider import GatewayStatus, IBKRBar
from app.db.models import PositionORM, WatchlistItemORM
from app.db.session import get_db
from app.main import app
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


def _hold_daily_ohlcv() -> pd.DataFrame:
    # Flat prices -- no Wave pullback ever qualifies, so this always resolves to HOLD
    # regardless of tide direction. Copied from tests/integration/test_stocks_analysis.py's
    # identically-named fixture.
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
        index=pd.date_range("2026-01-01", periods=30, freq="D", name="date"),
    )


def _hold_weekly_ohlcv() -> pd.DataFrame:
    """28 flat weeks, then a tiny up-week and a tiny down-week -- deliberately *not*
    perfectly flat throughout, to land on Tide NEUTRAL rather than BEARISH. See
    test_stocks_analysis.py's identically-shaped fixture docstring for why: a perfectly
    constant weekly close makes weekly EMA(13) and the weekly MACD-Histogram both exactly
    tied bar-over-bar, which `app.signals.impulse._direction`'s tie-counts-as-falling
    convention (reused by `evaluate_tide` for Screen 1, per `backend-weekly-impulse-
    screen1`) resolves to weekly Impulse RED / Tide BEARISH, not this fixture's intended
    NEUTRAL.
    """
    weekly_closes = [100.0] * 28 + [100.3, 100.1]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=30, freq="W", name="date"),
    )


def _bullish_weekly_ohlcv() -> pd.DataFrame:
    # 40 weeks of accelerating 5%/week growth -- BULLISH tide. Copied from
    # test_stocks_analysis.py's _buy_weekly_ohlcv.
    weekly_closes = [100 * (1.05**i) for i in range(40)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=40, freq="W", name="date"),
    )


def _bearish_weekly_ohlcv() -> pd.DataFrame:
    # Mirror image of _bullish_weekly_ohlcv -- BEARISH tide. Copied from
    # test_stocks_analysis.py's _sell_weekly_ohlcv.
    weekly_closes = [1000 * (0.9**i) for i in range(40)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=40, freq="W", name="date"),
    )


class _StubProvider:
    """A minimal DataProvider stand-in: returns a fixed HOLD-shaped daily frame plus a
    per-ticker weekly frame (HOLD-shaped/NEUTRAL-tide by default, or whatever `weekly`
    supplies for that ticker -- e.g. `_bullish_weekly_ohlcv()`/`_bearish_weekly_ohlcv()`) for
    every ticker in `computable`, or raises a fixed exception for every ticker in `failing`."""

    def __init__(
        self,
        *,
        computable: set[str] | None = None,
        failing: dict[str, Exception] | None = None,
        weekly: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        self._computable = computable or set()
        self._failing = failing or {}
        self._weekly = weekly or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise self._failing[ticker]
        return _hold_daily_ohlcv()

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise self._failing[ticker]
        return self._weekly.get(ticker, _hold_weekly_ohlcv())


def _make_client(db_session: Session, provider: _StubProvider) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture
def client(db_session: Session):
    test_client = _make_client(db_session, _StubProvider(computable={"AAPL"}))
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)


def _client_with_provider(db_session: Session, provider: _StubProvider) -> TestClient:
    return _make_client(db_session, provider)


class TestGetWatchlistEmpty:
    def test_empty_watchlist_returns_empty_items(self, client: TestClient) -> None:
        response = client.get("/api/watchlist")

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "trading_mode": {"mode": "swing", "day_trader_timeframe_triple": None},
        }


class TestAddWatchlistItem:
    def test_add_ticker_returns_201_with_null_signal_fields(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "AAPL"})

        assert response.status_code == 201
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["signal"] is None
        assert body["confidence"] is None
        assert body["confidence_band"] is None
        assert body["added_at"]

    def test_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "aapl"})

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_ticker_with_surrounding_whitespace_is_stripped_and_uppercased(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/watchlist", json={"ticker": " aapl "})

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_blank_ticker_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "   "})

        assert response.status_code == 422

    def test_duplicate_add_is_a_no_op_and_keeps_original_added_at(self, client: TestClient) -> None:
        first = client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert first.status_code == 201
        original_added_at = first.json()["added_at"]

        second = client.post("/api/watchlist", json={"ticker": "AAPL"})

        assert second.status_code == 201
        assert second.json()["added_at"] == original_added_at

        listed = client.get("/api/watchlist")
        assert len(listed.json()["items"]) == 1


class TestGetWatchlistWithSignal:
    def test_list_annotates_computable_ticker_with_signal(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        test_client = _client_with_provider(db_session, _StubProvider(computable={"AAPL"}))

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "AAPL"
        assert items[0]["signal"] == "HOLD"
        assert items[0]["confidence"] == 0
        assert items[0]["confidence_band"] == "Low"

    def test_list_nulls_out_signal_for_a_ticker_whose_fetch_fails(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="ZZZZ", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        provider = _StubProvider(failing={"ZZZZ": TickerNotFoundError("ZZZZ")})
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["ticker"] == "ZZZZ"
        assert item["signal"] is None
        assert item["confidence"] is None
        assert item["confidence_band"] is None

    def test_list_nulls_out_signal_for_a_ticker_with_insufficient_history(
        self, db_session: Session
    ) -> None:
        # Spot-test for InsufficientHistoryError specifically (a recent-IPO-shaped 422 from
        # the provider) -- TickerNotFoundError and DataProviderUnavailableError are covered
        # above; _compute_signal catches all three via the shared DataProviderError base, but
        # exercising each concrete subclass documents that every one of them nulls the entry
        # out rather than only the two already covered.
        db_session.add(WatchlistItemORM(ticker="IPOX", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        provider = _StubProvider(
            failing={"IPOX": InsufficientHistoryError("IPOX", available=5, required=26)}
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["ticker"] == "IPOX"
        assert item["signal"] is None
        assert item["confidence"] is None
        assert item["confidence_band"] is None

    def test_list_with_a_mix_of_computable_and_failing_tickers(self, db_session: Session) -> None:
        db_session.add_all(
            [
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
                WatchlistItemORM(ticker="ZZZZ", added_at=pd.Timestamp("2026-01-02").to_pydatetime()),
            ]
        )
        db_session.commit()
        provider = _StubProvider(
            computable={"AAPL"},
            failing={"ZZZZ": DataProviderUnavailableError("provider down")},
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["ticker"] for item in items] == ["AAPL", "ZZZZ"]
        assert items[0]["signal"] == "HOLD"
        assert items[1]["signal"] is None

    def test_list_is_ordered_by_added_at_oldest_first(self, db_session: Session) -> None:
        db_session.add_all(
            [
                WatchlistItemORM(ticker="MSFT", added_at=pd.Timestamp("2026-02-01").to_pydatetime()),
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
            ]
        )
        db_session.commit()
        test_client = _client_with_provider(
            db_session, _StubProvider(computable={"MSFT", "AAPL"})
        )

        response = test_client.get("/api/watchlist")

        assert [item["ticker"] for item in response.json()["items"]] == ["AAPL", "MSFT"]


class TestDeleteWatchlistItem:
    def test_delete_existing_item_returns_204(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        response = client.delete("/api/watchlist/AAPL")

        assert response.status_code == 204
        assert response.content == b""

    def test_deleted_item_no_longer_appears_in_list(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        client.delete("/api/watchlist/AAPL")

        assert client.get("/api/watchlist").json() == {
            "items": [],
            "trading_mode": {"mode": "swing", "day_trader_timeframe_triple": None},
        }

    def test_delete_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        response = client.delete("/api/watchlist/aapl")

        assert response.status_code == 204

    def test_delete_unknown_ticker_returns_404(self, client: TestClient) -> None:
        response = client.delete("/api/watchlist/ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]


class TestGetWatchlistBreadth:
    """GET /api/watchlist/breadth -- see this task's `decisions` entry for why this reuses
    the full `analyse()` pipeline (via `_tide_trend`) rather than calling `evaluate_tide`
    directly, and for the fresh-every-request (no aggregation-layer caching) choice."""

    def test_empty_watchlist_and_portfolio_returns_all_zero(self, client: TestClient) -> None:
        response = client.get("/api/watchlist/breadth")

        assert response.status_code == 200
        assert response.json() == {
            "tracked_ticker_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "unavailable_count": 0,
            "bullish_pct": 0.0,
            "bearish_pct": 0.0,
            "neutral_pct": 0.0,
        }

    def test_all_bullish_watchlist(self, db_session: Session) -> None:
        db_session.add_all(
            [
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
                WatchlistItemORM(ticker="MSFT", added_at=pd.Timestamp("2026-01-02").to_pydatetime()),
            ]
        )
        db_session.commit()
        provider = _StubProvider(
            computable={"AAPL", "MSFT"},
            weekly={"AAPL": _bullish_weekly_ohlcv(), "MSFT": _bullish_weekly_ohlcv()},
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist/breadth")

        assert response.status_code == 200
        body = response.json()
        assert body["tracked_ticker_count"] == 2
        assert body["bullish_count"] == 2
        assert body["bearish_count"] == 0
        assert body["neutral_count"] == 0
        assert body["unavailable_count"] == 0
        assert body["bullish_pct"] == 100.0
        assert body["bearish_pct"] == 0.0
        assert body["neutral_pct"] == 0.0

    def test_mixed_watchlist_and_portfolio_with_an_unavailable_ticker(
        self, db_session: Session
    ) -> None:
        # AAPL: BULLISH weekly, watchlist-only. MSFT: BEARISH weekly, portfolio-only.
        # GOOG: HOLD/NEUTRAL weekly (the provider's default), on *both* watchlist and
        # portfolio -- exercises the union/dedup (counted once, not twice). ZZZZ: fails to
        # fetch -- counted as unavailable_count, excluded from the percentages.
        db_session.add_all(
            [
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
                WatchlistItemORM(ticker="GOOG", added_at=pd.Timestamp("2026-01-02").to_pydatetime()),
                WatchlistItemORM(ticker="ZZZZ", added_at=pd.Timestamp("2026-01-03").to_pydatetime()),
            ]
        )
        db_session.add_all(
            [
                PositionORM(
                    id="pos-1",
                    ticker="MSFT",
                    quantity=10,
                    avg_cost_basis=100.0,
                    entry_date=pd.Timestamp("2026-01-01").date(),
                ),
                PositionORM(
                    id="pos-2",
                    ticker="GOOG",
                    quantity=5,
                    avg_cost_basis=50.0,
                    entry_date=pd.Timestamp("2026-01-01").date(),
                ),
            ]
        )
        db_session.commit()
        provider = _StubProvider(
            computable={"AAPL", "GOOG", "MSFT"},
            failing={"ZZZZ": TickerNotFoundError("ZZZZ")},
            weekly={"AAPL": _bullish_weekly_ohlcv(), "MSFT": _bearish_weekly_ohlcv()},
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist/breadth")

        assert response.status_code == 200
        body = response.json()
        assert body["tracked_ticker_count"] == 4  # AAPL, GOOG, MSFT, ZZZZ -- GOOG counted once
        assert body["bullish_count"] == 1
        assert body["bearish_count"] == 1
        assert body["neutral_count"] == 1
        assert body["unavailable_count"] == 1
        # Percentages are of the 3 computable tickers, not all 4 tracked.
        assert body["bullish_pct"] == pytest.approx(33.3)
        assert body["bearish_pct"] == pytest.approx(33.3)
        assert body["neutral_pct"] == pytest.approx(33.3)


def _ibkr_bars(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    *,
    start: datetime,
    step_minutes: int,
) -> list[IBKRBar]:
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close,
            high=highs[i],
            low=lows[i],
            close=close,
            volume=volumes[i],
        )
        for i, close in enumerate(closes)
    ]


def _day_trader_long_term_bars() -> list[IBKRBar]:
    closes = [100 * (1.05**i) for i in range(40)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1_000_000.0] * 40
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60)


def _day_trader_intermediate_bars() -> list[IBKRBar]:
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    closes.append(closes[-1] - 1.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [1_000_000.0] * 25 + [9_000_000.0, 3_000_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10)


def _day_trader_short_term_bars() -> list[IBKRBar]:
    closes = [95.5, 99.5]
    highs = [96.0, 100.0]
    lows = [94.0, 98.5]
    volumes = [500_000.0, 500_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2)


_FULLY_INTRADAY_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)


class _StubIBKRProvider:
    """Same convention as tests/integration/test_stocks_analysis.py's own `_StubIBKRProvider`
    (itself matching tests/integration/test_ibkr_scanner.py's)."""

    def __init__(
        self,
        *,
        resolve_conid_result: int | None | Exception = 999,
        get_hourly_bars_by_bar_size: dict[str, list[IBKRBar] | Exception] | None = None,
        gateway_status: GatewayStatus | None = None,
    ) -> None:
        self._resolve_conid_result = resolve_conid_result
        self._get_hourly_bars_by_bar_size = get_hourly_bars_by_bar_size or {}
        self._gateway_status = gateway_status or GatewayStatus(state="available")

    def resolve_conid(self, ticker: str) -> int | None:
        if isinstance(self._resolve_conid_result, Exception):
            raise self._resolve_conid_result
        return self._resolve_conid_result

    def get_hourly_bars(self, conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
        result = self._get_hourly_bars_by_bar_size[bar_size]
        if isinstance(result, Exception):
            raise result
        return result

    def get_gateway_status(self) -> GatewayStatus:
        return self._gateway_status


def _all_legs_available_ibkr_provider() -> _StubIBKRProvider:
    return _StubIBKRProvider(
        get_hourly_bars_by_bar_size={
            "1h": _day_trader_long_term_bars(),
            "10min": _day_trader_intermediate_bars(),
            "2min": _day_trader_short_term_bars(),
        }
    )


def _client_with_ibkr(
    db_session: Session, provider: _StubProvider, ibkr_provider: object | None
) -> TestClient:
    test_client = _make_client(db_session, provider)
    app.dependency_overrides[get_ibkr_provider] = lambda: ibkr_provider
    return test_client


class TestDayTraderMode:
    """`GET /api/watchlist`/`GET /api/watchlist/breadth` while the global trading mode is
    `day_trader` (`backend-day-trader-timeframe-mode-api`) -- exercises `_compute_signal`'s
    `compute_day_trader_signal` branch end to end through both routes, via the shared
    `app.api.day_trader_signal` orchestration `GET /api/stocks/{ticker}/analysis` also uses
    (see tests/integration/test_stocks_analysis.py's own `TestDayTraderMode` for the
    unavailable-data-case coverage; this class focuses on this router's own
    null-signal-not-failed-request contract)."""

    @pytest.fixture(autouse=True)
    def _clear_overrides(self):
        """Pops every `app.dependency_overrides` entry `_client_with_ibkr`/`_make_client` set
        for this class's tests (`get_db`/`get_data_provider`/`get_ibkr_provider`), not just
        `get_ibkr_provider` -- this class is (as of backend-day-trader-timeframe-mode-api's own
        PR #313) the last class in this file, so leaving `get_db`/`get_data_provider` registered
        process-wide after its last test would otherwise leak a disposed in-memory SQLite
        session and a stale `_StubProvider` into any later-collected test elsewhere in the suite
        that hits a DB-or-provider-backed route via an unguarded `TestClient(app)` -- a latent,
        collection-order-dependent flakiness risk (non-blocking finding from PR #313's round-2
        review, backend-day-trader-timeframe-mode-api-followups.json). Named more generally than
        the `get_ibkr_provider`-only original (`_clear_ibkr_override`) to reflect that it now
        covers all three."""
        yield
        app.dependency_overrides.pop(get_ibkr_provider, None)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)

    def test_watchlist_item_gets_a_real_day_trader_mode_signal(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        test_client = _client_with_ibkr(
            db_session, _StubProvider(), _all_legs_available_ibkr_provider()
        )

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "day_trader"
        item = body["items"][0]
        assert item["ticker"] == "AAPL"
        assert item["signal"] == "BUY"
        assert 0 <= item["confidence"] <= 100

    def test_watchlist_item_nulls_out_signal_when_ibkr_disabled(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        test_client = _client_with_ibkr(db_session, _StubProvider(), ibkr_provider=None)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "day_trader"
        item = body["items"][0]
        assert item["signal"] is None
        assert item["confidence"] is None
        assert item["confidence_band"] is None

    def test_watchlist_item_nulls_out_signal_for_non_fully_intraday_triple(
        self, db_session: Session
    ) -> None:
        mixed_triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("30m"),
            short_term=TimeframeInterval.parse("5m"),
        )
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=mixed_triple
        )
        db_session.commit()
        test_client = _client_with_ibkr(
            db_session, _StubProvider(), _all_legs_available_ibkr_provider()
        )

        response = test_client.get("/api/watchlist")

        assert response.json()["items"][0]["signal"] is None

    def test_breadth_counts_a_day_trader_mode_ticker_as_unavailable_when_ibkr_disabled(
        self, db_session: Session
    ) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        test_client = _client_with_ibkr(db_session, _StubProvider(), ibkr_provider=None)

        response = test_client.get("/api/watchlist/breadth")

        assert response.status_code == 200
        body = response.json()
        assert body["tracked_ticker_count"] == 1
        assert body["unavailable_count"] == 1
        assert body["bullish_count"] == 0

    def test_breadth_counts_a_day_trader_mode_ticker_as_bullish_when_available(
        self, db_session: Session
    ) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        test_client = _client_with_ibkr(
            db_session, _StubProvider(), _all_legs_available_ibkr_provider()
        )

        response = test_client.get("/api/watchlist/breadth")

        assert response.status_code == 200
        body = response.json()
        assert body["tracked_ticker_count"] == 1
        assert body["bullish_count"] == 1
        assert body["unavailable_count"] == 0
