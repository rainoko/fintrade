"""Integration tests for GET /api/stocks/{ticker}/history (app/api/routers/stocks.py).

Uses a stub `DataProvider` (via a `get_data_provider` dependency override, same pattern as
tests/integration/test_stocks_analysis.py) so these tests never touch a live market data
provider or the SQLite cache underneath it.
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


def _get_history(provider: _StubProvider, ticker: str = "AAPL", **params):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/history", params=params)
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _daily_ohlcv(n: int = 400, start: str = "2025-01-01") -> pd.DataFrame:
    closes = [100 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        },
        index=pd.date_range(start, periods=n, freq="D", name="date"),
    )


def _weekly_ohlcv(n: int = 30, start: str = "2025-01-01") -> pd.DataFrame:
    closes = [100 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [500_000] * n,
        },
        index=pd.date_range(start, periods=n, freq="W", name="date"),
    )


class TestGetHistory:
    def test_default_daily_response_shape(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=30)})

        response = _get_history(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["interval"] == "daily"
        assert len(body["bars"]) == 30
        bar = body["bars"][0]
        assert set(bar) == {"date", "open", "high", "low", "close", "volume"}

    def test_weekly_interval_uses_weekly_provider_method(self) -> None:
        provider = _StubProvider(weekly={"AAPL": _weekly_ohlcv(n=30)})

        response = _get_history(provider, interval="weekly")

        assert response.status_code == 200
        body = response.json()
        assert body["interval"] == "weekly"
        assert len(body["bars"]) == 30

    def test_range_1y_trims_to_trailing_year_from_last_bar(self) -> None:
        # 400 daily bars starting 2025-01-01 -> last bar is well past one year out, so a
        # '1y' range should trim to (roughly) 365 of the 400 bars, anchored on the last bar.
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=400)})

        response = _get_history(provider, range="1y")

        assert response.status_code == 200
        bars = response.json()["bars"]
        full = _daily_ohlcv(n=400)
        expected_cutoff = full.index[-1] - pd.DateOffset(years=1)
        expected_count = int((full.index > expected_cutoff).sum())
        assert len(bars) == expected_count
        assert bars[-1]["date"] == full.index[-1].date().isoformat()

    def test_range_4w_trims_to_last_4_weeks(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=100)})

        response = _get_history(provider, range="4w")

        assert response.status_code == 200
        bars = response.json()["bars"]
        full = _daily_ohlcv(n=100)
        expected_cutoff = full.index[-1] - pd.DateOffset(weeks=4)
        expected_count = int((full.index > expected_cutoff).sum())
        assert len(bars) == expected_count

    def test_range_6m_trims_to_trailing_six_months(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=400)})

        response = _get_history(provider, range="6m")

        assert response.status_code == 200
        bars = response.json()["bars"]
        full = _daily_ohlcv(n=400)
        expected_cutoff = full.index[-1] - pd.DateOffset(months=6)
        expected_count = int((full.index > expected_cutoff).sum())
        assert len(bars) == expected_count

    def test_range_2y_trims_to_trailing_two_years(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=800)})

        response = _get_history(provider, range="2y")

        assert response.status_code == 200
        bars = response.json()["bars"]
        full = _daily_ohlcv(n=800)
        expected_cutoff = full.index[-1] - pd.DateOffset(years=2)
        expected_count = int((full.index > expected_cutoff).sum())
        assert len(bars) == expected_count

    def test_range_max_returns_full_history(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=400)})

        response = _get_history(provider, range="max")

        assert response.status_code == 200
        assert len(response.json()["bars"]) == 400

    def test_range_30d_trims_to_last_30_days(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=100)})

        response = _get_history(provider, range="30d")

        assert response.status_code == 200
        assert len(response.json()["bars"]) == 30

    def test_invalid_range_returns_422(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=10)})

        response = _get_history(provider, range="banana")

        assert response.status_code == 422

    def test_ticker_is_uppercased(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=10)})

        response = _get_history(provider, ticker="aapl")

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    def test_unknown_ticker_returns_404(self) -> None:
        provider = _StubProvider(failing_daily={"ZZZZ": TickerNotFoundError("ZZZZ")})

        response = _get_history(provider, ticker="ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]

    def test_insufficient_weekly_history_returns_422(self) -> None:
        provider = _StubProvider(
            failing_weekly={"AAPL": InsufficientHistoryError("AAPL", available=5, required=26)}
        )

        response = _get_history(provider, interval="weekly")

        assert response.status_code == 422
        assert "AAPL" in response.json()["detail"]

    def test_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            failing_daily={"AAPL": DataProviderUnavailableError("both providers failed for AAPL")}
        )

        response = _get_history(provider)

        assert response.status_code == 503

    def test_empty_history_returns_empty_bars(self) -> None:
        provider = _StubProvider(daily={"AAPL": _daily_ohlcv(n=0)})

        response = _get_history(provider)

        assert response.status_code == 200
        assert response.json()["bars"] == []
