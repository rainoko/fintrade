"""Tests for app.data.yfinance_provider.YFinanceProvider (docs/Analyse.md §9,
docs/architecture/Backend.md §2).

Per docs/architecture/Testing.md ("Data provider adapters are tested against
recorded fixtures ... never live network calls"), every test here mocks
``yfinance.Ticker`` itself and feeds it a DataFrame loaded from a CSV fixture
under tests/fixtures/yfinance/ -- see this task's `decisions` entry on
docs/tasks/data-provider-yfinance.json for why the fixture format is "a saved
DataFrame shaped like yfinance's own `Ticker.history()` return value" rather
than raw Yahoo Chart API JSON.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.yfinance_provider import YFinanceProvider

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "yfinance"


def _load_fixture(name: str) -> pd.DataFrame:
    """Load a recorded yfinance ``Ticker.history()`` response from CSV, restoring
    the tz-aware DatetimeIndex shape a real response has.
    """
    df = pd.read_csv(FIXTURES_DIR / f"{name}.csv", index_col="Date")
    if len(df) > 0:
        # DST means the recorded offset isn't constant across rows (-04:00 vs
        # -05:00); parse via UTC first, then convert, rather than letting
        # read_csv/DatetimeIndex infer a single fixed offset.
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    else:
        df.index = pd.DatetimeIndex(df.index)
    return df


class TestGetDailyOhlcv:
    def test_returns_normalized_columns_indexed_by_date(self, mocker) -> None:
        raw = _load_fixture("aapl_daily")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
        assert len(result) == len(raw)
        # tz-naive: downstream indicator/date arithmetic shouldn't have to
        # care about the exchange timezone yfinance attaches.
        assert result.index.tz is None
        assert result["close"].iloc[0] == pytest.approx(raw["Close"].iloc[0])

    def test_requests_daily_interval_with_full_history(self, mocker) -> None:
        raw = _load_fixture("aapl_daily")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mock_ticker_cls = mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        YFinanceProvider().get_daily_ohlcv("AAPL")

        mock_ticker_cls.assert_called_once_with("AAPL")
        mock_ticker.history.assert_called_once_with(period="max", interval="1d")

    def test_unknown_ticker_raises_ticker_not_found(self, mocker) -> None:
        raw = _load_fixture("unknown_empty")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(TickerNotFoundError) as exc_info:
            YFinanceProvider().get_daily_ohlcv("NOTAREALTICKER")

        assert exc_info.value.ticker == "NOTAREALTICKER"

    def test_rate_limit_raises_data_provider_unavailable(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = YFRateLimitError()
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(DataProviderUnavailableError):
            YFinanceProvider().get_daily_ohlcv("AAPL")

    def test_unexpected_yfinance_failure_raises_data_provider_unavailable(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = ConnectionError("boom")
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(DataProviderUnavailableError):
            YFinanceProvider().get_daily_ohlcv("AAPL")

    def test_tz_naive_response_is_passed_through_unchanged(self, mocker) -> None:
        """Not every yfinance response is guaranteed tz-aware (fixtures, or a
        future yfinance version) -- the tz-strip step must be a no-op rather
        than error when there's no tz to strip.
        """
        raw = _load_fixture("aapl_daily")
        raw.index = raw.index.tz_localize(None)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_daily_ohlcv("AAPL")

        assert result.index.tz is None
        assert len(result) == len(raw)


class TestGetWeeklyOhlcv:
    def test_returns_normalized_columns_using_native_weekly_interval(self, mocker) -> None:
        raw = _load_fixture("aapl_weekly")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mock_ticker_cls = mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_weekly_ohlcv("AAPL")

        mock_ticker_cls.assert_called_once_with("AAPL")
        mock_ticker.history.assert_called_once_with(period="max", interval="1wk")
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert len(result) == len(raw) == 60

    def test_unknown_ticker_raises_ticker_not_found(self, mocker) -> None:
        raw = _load_fixture("unknown_empty")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(TickerNotFoundError):
            YFinanceProvider().get_weekly_ohlcv("NOTAREALTICKER")

    def test_fewer_than_26_weeks_raises_insufficient_history(self, mocker) -> None:
        raw = _load_fixture("newco_weekly_short")
        assert len(raw) == 10  # sanity check on the fixture itself
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(InsufficientHistoryError) as exc_info:
            YFinanceProvider().get_weekly_ohlcv("NEWCO")

        assert exc_info.value.ticker == "NEWCO"
        assert exc_info.value.available == 10
        assert exc_info.value.required == 26

    def test_exactly_26_weeks_does_not_raise(self, mocker) -> None:
        raw = _load_fixture("aapl_weekly").iloc[:26]
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_weekly_ohlcv("AAPL")

        assert len(result) == 26

    def test_rate_limit_raises_data_provider_unavailable(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = YFRateLimitError()
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        with pytest.raises(DataProviderUnavailableError):
            YFinanceProvider().get_weekly_ohlcv("AAPL")
