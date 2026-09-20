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

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
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


def _insider_transactions_df() -> pd.DataFrame:
    """Shaped like yfinance's own `Ticker.insider_transactions` (see
    `yfinance.scrapers.holders.Holders._parse_insider_transactions`'s column-rename map)."""
    return pd.DataFrame(
        {
            "Insider": ["Cook Timothy D", "Maestri Luca"],
            "Position": ["Chief Executive Officer", "Chief Financial Officer"],
            "URL": ["https://example.com/a", "https://example.com/b"],
            "Transaction": ["Sale", "Sale"],
            "Text": [
                "Sale at price 220.00 - 225.00 per share.",
                "Sale at price 218.50 per share.",
            ],
            "Shares": [50_000.0, 12_000.0],
            "Value": [11_125_000.0, 2_622_000.0],
            "Start Date": [pd.Timestamp("2026-08-15"), pd.Timestamp("2026-08-10")],
            "Ownership": ["D", "D"],
        }
    )


class TestGetExtendedData:
    def test_full_response_maps_calendar_info_and_insider_transactions(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.calendar = {
            "Dividend Date": date(2026, 11, 20),
            "Ex-Dividend Date": date(2026, 11, 15),
            "Earnings Date": [date(2026, 10, 29), date(2026, 10, 30)],
        }
        mock_ticker.info = {
            "sharesShort": 12_345_678,
            "shortRatio": 2.3,
            "shortPercentOfFloat": 0.045,
            "sharesShortPriorMonth": 13_000_000,
            "floatShares": 1_000_000_000,
        }
        mock_ticker.insider_transactions = _insider_transactions_df()
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("AAPL")

        # Earliest of the two "Earnings Date" entries -- Yahoo's own unconfirmed-window
        # convention (see get_extended_data's docstring).
        assert result.earnings_date == date(2026, 10, 29)
        assert result.ex_dividend_date == date(2026, 11, 15)
        assert result.shares_short == 12_345_678
        assert result.short_ratio == pytest.approx(2.3)
        assert result.short_percent_of_float == pytest.approx(0.045)
        assert result.float_shares == 1_000_000_000
        assert result.unavailable_reason is None
        assert len(result.insider_transactions) == 2
        first = result.insider_transactions[0]
        assert first.insider == "Cook Timothy D"
        assert first.position == "Chief Executive Officer"
        assert first.transaction_text == "Sale at price 220.00 - 225.00 per share."
        assert first.shares == pytest.approx(50_000.0)
        assert first.value == pytest.approx(11_125_000.0)
        assert first.start_date == date(2026, 8, 15)
        assert first.ownership == "D"

    def test_missing_calendar_info_and_insider_transactions_yield_all_none(self, mocker) -> None:
        """yfinance's own data can be incomplete for smaller tickers (docs/ideas.md) --
        an empty calendar/info dict and a `None` insider_transactions frame must degrade to a
        fully-null/empty result, not raise."""
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker.info = {}
        mock_ticker.insider_transactions = None
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("SMALLCAP")

        assert result.earnings_date is None
        assert result.ex_dividend_date is None
        assert result.shares_short is None
        assert result.short_ratio is None
        assert result.short_percent_of_float is None
        assert result.float_shares is None
        assert result.insider_transactions == []
        assert result.unavailable_reason is None

    def test_nan_insider_transaction_string_fields_map_to_none(self, mocker) -> None:
        """`Insider`/`Position`/`Ownership` can themselves be NaN on an incomplete filing row
        (`_str_or_none`'s NaN-float branch), not just the numeric `info` fields above."""
        df = pd.DataFrame(
            {
                "Insider": [np.nan],
                "Position": [np.nan],
                "URL": ["https://example.com/a"],
                "Transaction": ["Sale"],
                "Text": ["Sale at price 220.00 per share."],
                "Shares": [1_000.0],
                "Value": [220_000.0],
                "Start Date": [pd.Timestamp("2026-08-15")],
                "Ownership": [np.nan],
            }
        )
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker.info = {}
        mock_ticker.insider_transactions = df
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("AAPL")

        assert len(result.insider_transactions) == 1
        transaction = result.insider_transactions[0]
        assert transaction.insider is None
        assert transaction.position is None
        assert transaction.ownership is None
        assert transaction.transaction_text == "Sale at price 220.00 per share."

    def test_empty_insider_transactions_frame_yields_empty_list(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker.info = {}
        mock_ticker.insider_transactions = pd.DataFrame()
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("AAPL")

        assert result.insider_transactions == []

    def test_nan_info_fields_map_to_none(self, mocker) -> None:
        """A field yfinance's own JSON populated as NaN (rather than omitting it outright)
        must still map to `None`, not a Pydantic-rejecting float('nan')."""
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker.info = {
            "sharesShort": np.nan,
            "shortRatio": np.nan,
            "shortPercentOfFloat": np.nan,
            "floatShares": np.nan,
        }
        mock_ticker.insider_transactions = pd.DataFrame()
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("AAPL")

        assert result.shares_short is None
        assert result.short_ratio is None
        assert result.short_percent_of_float is None
        assert result.float_shares is None

    def test_none_calendar_is_treated_as_empty(self, mocker) -> None:
        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        mock_ticker.info = None
        mock_ticker.insider_transactions = None
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_extended_data("AAPL")

        assert result.earnings_date is None
        assert result.insider_transactions == []

    def test_rate_limit_raises_data_provider_unavailable(self, mocker) -> None:
        mock_ticker_cls = mocker.patch("app.data.yfinance_provider.yf.Ticker")
        mock_ticker_cls.side_effect = YFRateLimitError()

        with pytest.raises(DataProviderUnavailableError):
            YFinanceProvider().get_extended_data("AAPL")

    def test_unexpected_failure_raises_data_provider_unavailable(self, mocker) -> None:
        mock_ticker_cls = mocker.patch("app.data.yfinance_provider.yf.Ticker")
        mock_ticker_cls.side_effect = ConnectionError("boom")

        with pytest.raises(DataProviderUnavailableError):
            YFinanceProvider().get_extended_data("AAPL")
