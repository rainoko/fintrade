"""Integration tests for GET /api/stocks/{ticker}/indicators (app/api/routers/stocks.py).

Uses a stub `DataProvider` (via a `get_data_provider` dependency override, same pattern as
tests/integration/test_stocks_analysis.py and test_stocks_history.py) so these tests never
touch a live market data provider or the SQLite cache underneath it.
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


def _get_indicator_history(provider: _StubProvider, ticker: str = "AAPL", **params):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/indicators", params=params)
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _get_analysis(provider: _StubProvider, ticker: str = "AAPL"):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/analysis")
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _buy_daily_ohlcv() -> pd.DataFrame:
    # 20 days of a gentle uptrend, then a 5-day steep selloff on elevated volume (an oversold
    # pullback), then one more day rallying sharply back above the prior day's high (the
    # Trigger) -- copied from tests/integration/test_stocks_analysis.py's matching fixture.
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
    # A plain list, not a pd.Series -- see test_stocks_analysis.py's _buy_weekly_ohlcv comment
    # for why (a Series column's own default RangeIndex would otherwise reindex against this
    # DataFrame's explicit DatetimeIndex, silently turning every value NaN).
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


class TestGetIndicatorHistory:
    def test_response_shape(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert len(body["points"]) == len(_buy_daily_ohlcv())
        point = body["points"][0]
        assert set(point) == {
            "date",
            "ema_13",
            "ema_26",
            "macd_histogram",
            "bull_power",
            "bear_power",
            "stochastic_k",
            "force_index_2ema",
            "signal",
            "confidence",
            "confidence_band",
        }

    def test_points_are_oldest_first(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider)

        dates = [point["date"] for point in response.json()["points"]]
        assert dates == sorted(dates)
        assert dates[0] == _buy_daily_ohlcv().index[0].date().isoformat()
        assert dates[-1] == _buy_daily_ohlcv().index[-1].date().isoformat()

    def test_last_point_matches_analysis_endpoint_for_same_ticker(self) -> None:
        """No drift between the two endpoints: the historical series' last (most recent)
        entry must match GET /api/stocks/{ticker}/analysis's signal/confidence/indicators for
        the same ticker at the same as_of date -- both are produced from the exact same
        analyse() call over the exact same (untruncated) inputs."""
        provider = _StubProvider(
            daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        history_response = _get_indicator_history(provider)
        analysis_response = _get_analysis(provider)

        assert history_response.status_code == analysis_response.status_code == 200
        last_point = history_response.json()["points"][-1]
        analysis = analysis_response.json()

        assert last_point["date"] == analysis["as_of"]
        assert last_point["signal"] == analysis["signal"] == "BUY"
        assert last_point["confidence"] == analysis["confidence"]
        assert last_point["confidence_band"] == analysis["confidence_band"]
        assert last_point["ema_13"] == analysis["indicators"]["ema_13"]
        assert last_point["ema_26"] == analysis["indicators"]["ema_26"]
        assert last_point["macd_histogram"] == analysis["indicators"]["macd_histogram"]
        assert last_point["bull_power"] == analysis["indicators"]["bull_power"]
        assert last_point["bear_power"] == analysis["indicators"]["bear_power"]
        assert last_point["stochastic_k"] == analysis["screens"]["wave"]["stochastic_k"]
        assert last_point["force_index_2ema"] == analysis["screens"]["wave"]["force_index_2ema"]

    def test_hold_signal_has_zero_confidence(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 200
        points = response.json()["points"]
        assert all(point["signal"] == "HOLD" for point in points)
        assert all(point["confidence"] == 0 for point in points)
        assert all(point["confidence_band"] == "Low" for point in points)

    def test_range_1y_trims_to_trailing_year_from_last_bar(self) -> None:
        daily = _hold_daily_ohlcv(n=400)
        weekly = _hold_weekly_ohlcv(n=60)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_indicator_history(provider, range="1y")

        assert response.status_code == 200
        points = response.json()["points"]
        expected_cutoff = daily.index[-1] - pd.DateOffset(years=1)
        expected_count = int((daily.index > expected_cutoff).sum())
        assert len(points) == expected_count
        assert points[-1]["date"] == daily.index[-1].date().isoformat()

    def test_range_max_returns_full_history(self) -> None:
        daily = _hold_daily_ohlcv(n=100)
        weekly = _hold_weekly_ohlcv(n=30)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_indicator_history(provider, range="max")

        assert response.status_code == 200
        assert len(response.json()["points"]) == 100

    def test_range_trimming_does_not_degrade_indicator_warm_up(self) -> None:
        """A range-trimmed window's emitted points must still reflect the *full* available
        history for indicator warm-up (EMA/MACD/Stochastic), not just the trimmed window --
        i.e. trimming controls what's returned, not what feeds the computation. Confirmed by
        checking the last point (present in both an untrimmed and a trimmed response) is
        identical either way."""
        daily = _buy_daily_ohlcv()
        weekly = _buy_weekly_ohlcv()
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        full_response = _get_indicator_history(provider, range="max")
        trimmed_response = _get_indicator_history(provider, range="7d")

        assert full_response.status_code == trimmed_response.status_code == 200
        assert full_response.json()["points"][-1] == trimmed_response.json()["points"][-1]

    def test_early_bars_have_null_stochastic_k_and_force_index(self) -> None:
        """stochastic_k/force_index_2ema are the only two IndicatorHistoryPoint fields that
        can legitimately be null -- the first k_period-1+smooth-1=6 bars have no full
        Stochastic %K(5,3,3) warm-up window (app.indicators.stochastic.stochastic_oscillator's
        own docstring), and the very first bar has no prior close for Force Index's raw
        volume*close.diff() input (app.indicators.force_index.force_index's own docstring).
        Every other bar is unaffected: EMA/MACD-Histogram/Bull/Bear Power never produce NaN
        even on the first bar, since pandas' ewm seeds from the first observation instead of
        requiring a full window. See this task's `decisions` entry for why the schema marks
        only these two fields Optional rather than trimming warmed-up-insufficient points
        out of the response entirely."""
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 200
        points = response.json()["points"]
        assert points[0]["force_index_2ema"] is None
        assert all(point["stochastic_k"] is None for point in points[:6])
        assert all(point["stochastic_k"] is not None for point in points[6:])
        assert all(point["force_index_2ema"] is not None for point in points[1:])
        # Every other field stays non-null across the whole warm-up window.
        for point in points:
            assert point["ema_13"] is not None
            assert point["ema_26"] is not None
            assert point["macd_histogram"] is not None
            assert point["bull_power"] is not None
            assert point["bear_power"] is not None

    def test_invalid_range_returns_422(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider, range="banana")

        assert response.status_code == 422

    def test_range_within_digit_cap_but_out_of_timestamp_bounds_returns_422(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider, range="9999y")

        assert response.status_code == 422

    def test_ticker_is_uppercased(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_indicator_history(provider, ticker="aapl")

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    def test_unknown_ticker_returns_404(self) -> None:
        provider = _StubProvider(failing_daily={"ZZZZ": TickerNotFoundError("ZZZZ")})

        response = _get_indicator_history(provider, ticker="ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]

    def test_insufficient_weekly_history_returns_422(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": InsufficientHistoryError("AAPL", available=5, required=26)
            },
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 422
        assert "AAPL" in response.json()["detail"]

    def test_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            failing_daily={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            }
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 503

    def test_weekly_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            },
        )

        response = _get_indicator_history(provider)

        assert response.status_code == 503

    def test_empty_history_returns_empty_points_list(self) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        provider = _StubProvider(daily={"AAPL": empty}, weekly={"AAPL": empty})

        response = _get_indicator_history(provider)

        assert response.status_code == 200
        assert response.json()["points"] == []
