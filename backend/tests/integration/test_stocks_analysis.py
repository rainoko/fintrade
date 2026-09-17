"""Integration tests for GET /api/stocks/{ticker}/analysis (app/api/routers/stocks.py).

Uses a stub `DataProvider` (via a `get_data_provider` dependency override, same pattern as
tests/integration/test_portfolio_get.py) so these tests never touch a live market data
provider. This endpoint has no DB dependency of its own, so there's no `get_db` override here.

The BUY/SELL/HOLD fixtures below are copied verbatim from
tests/unit/signals/test_engine.py's `TestAnalyseEndToEnd` (the real, unmocked
Screen/gate/indicator composition already has exhaustive hand-derived coverage there); these
tests instead focus on this route's own job -- wiring the provider fetch, `analyse()` call, and
`AnalysisResponse` mapping together, plus the 404/422/503 error mapping.
"""

import pandas as pd
from fastapi.testclient import TestClient

from app.api.dependencies import get_data_provider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.main import app


class _StubProvider:
    """A minimal DataProvider stand-in: returns fixed daily/weekly frames per ticker, or
    raises a fixed exception for tickers listed in the relevant `failing_*` set."""

    def __init__(
        self,
        *,
        daily: dict[str, pd.DataFrame] | None = None,
        weekly: dict[str, pd.DataFrame] | None = None,
        failing_daily: dict[str, Exception] | None = None,
        failing_weekly: dict[str, Exception] | None = None,
    ) -> None:
        self._daily = daily or {}
        self._weekly = weekly or {}
        self._failing_daily = failing_daily or {}
        self._failing_weekly = failing_weekly or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_daily:
            raise self._failing_daily[ticker]
        return self._daily[ticker]

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_weekly:
            raise self._failing_weekly[ticker]
        return self._weekly[ticker]


def _make_client(provider: _StubProvider) -> TestClient:
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


def _get_analysis(provider: _StubProvider, ticker: str = "AAPL"):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/analysis")
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _buy_daily_ohlcv() -> pd.DataFrame:
    # 20 days of a gentle uptrend, then a 5-day steep selloff on elevated volume (an oversold
    # pullback), then one more day rallying sharply back above the prior day's high (the
    # Trigger) -- copied from test_engine.py's test_end_to_end_buy_after_pullback_and_trigger.
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _buy_weekly_ohlcv() -> pd.DataFrame:
    # 40 weeks of accelerating 5%/week growth -- BULLISH tide. `weekly_closes` is built as a
    # plain array (not a pd.Series) before assembling the DataFrame with an explicit
    # DatetimeIndex below -- a Series column carries its own (default RangeIndex) index, which
    # pandas would otherwise reindex against the DataFrame's DatetimeIndex on construction,
    # silently turning every value NaN since the two indexes share no labels.
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


def _sell_daily_ohlcv() -> pd.DataFrame:
    # Mirror image of the BUY fixture: gentle downtrend, then a 5-day steep rebound rally on
    # elevated volume, then one more day selling off sharply back below the prior day's low.
    closes = [100 - i * 0.5 for i in range(20)]
    closes += [closes[-1] + 3 * i for i in range(1, 6)]
    closes.append(closes[-1] - 8.0)
    volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _sell_weekly_ohlcv() -> pd.DataFrame:
    # Same plain-array-not-Series reasoning as _buy_weekly_ohlcv above.
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


def _hold_daily_ohlcv() -> pd.DataFrame:
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
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
        index=pd.date_range("2025-01-01", periods=30, freq="W", name="date"),
    )


class TestGetAnalysis:
    def test_buy_signal_response_shape(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["as_of"] == _buy_daily_ohlcv().index[-1].date().isoformat()
        assert body["signal"] == "BUY"
        assert 0 <= body["confidence"] <= 100
        assert body["confidence_band"] in ("Low", "Medium", "High")
        assert body["screens"]["tide"]["trend"] == "BULLISH"
        assert len(body["confidence_breakdown"]) == 5
        assert set(body["indicators"]) == {
            "ema_13",
            "ema_26",
            "macd_histogram",
            "bull_power",
            "bear_power",
        }

    def test_malformed_latest_daily_bar_is_excluded_not_nulled(self) -> None:
        """Regression test for the real, observed yfinance condition this task fixes: the
        most recent daily bar can come back with NaN open/high/low/close and only volume
        populated. `app.signals.engine.drop_malformed_daily_bars` excludes such a bar before
        analysis rather than letting it leak `null` into the (non-Optional)
        `Indicators`/`WaveScreen` schema fields, so `as_of` should reflect the last *real*
        bar's date, not the malformed one, and every indicator field should still be a real
        number.
        """
        clean_daily = _buy_daily_ohlcv()
        malformed_row = pd.DataFrame(
            {
                "open": [float("nan")],
                "high": [float("nan")],
                "low": [float("nan")],
                "close": [float("nan")],
                "volume": [500_000],
            },
            index=pd.DatetimeIndex(
                [clean_daily.index[-1] + pd.DateOffset(days=1)], name="date"
            ),
        )
        daily_with_malformed_latest_bar = pd.concat([clean_daily, malformed_row])
        provider = _StubProvider(
            daily={"AAPL": daily_with_malformed_latest_bar}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "BUY"
        # as_of reflects the last real bar, not the malformed (later-dated) one.
        assert body["as_of"] == clean_daily.index[-1].date().isoformat()
        for field, value in body["indicators"].items():
            assert isinstance(value, (int, float)), f"indicators.{field} was {value!r}, not a number"
        assert body["screens"]["wave"]["stochastic_k"] is not None
        assert body["screens"]["wave"]["force_index_2ema"] is not None

    def test_sell_signal_response_shape(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _sell_daily_ohlcv()}, weekly={"AAPL": _sell_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "SELL"
        assert body["screens"]["tide"]["trend"] == "BEARISH"
        assert len(body["confidence_breakdown"]) == 5

    def test_hold_signal_has_zero_confidence_and_empty_breakdown(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "HOLD"
        assert body["confidence"] == 0
        assert body["confidence_band"] == "Low"
        assert body["confidence_breakdown"] == []

    def test_ticker_is_uppercased(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_analysis(provider, ticker="aapl")

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    def test_unknown_ticker_returns_404(self) -> None:
        provider = _StubProvider(failing_daily={"ZZZZ": TickerNotFoundError("ZZZZ")})

        response = _get_analysis(provider, ticker="ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]

    def test_insufficient_weekly_history_returns_422(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": InsufficientHistoryError("AAPL", available=5, required=26)
            },
        )

        response = _get_analysis(provider)

        assert response.status_code == 422
        assert "AAPL" in response.json()["detail"]

    def test_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            failing_daily={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            }
        )

        response = _get_analysis(provider)

        assert response.status_code == 503

    def test_weekly_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            },
        )

        response = _get_analysis(provider)

        assert response.status_code == 503
