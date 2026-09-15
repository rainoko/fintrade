import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from app.data.base import DataProvider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)

# Screen 1 needs at least 26 weeks of history to seed the 26-week EMA
# (docs/Analyse.md §8: "minimum ~200 trading days, to seed 26-week/weekly
# EMA & MACD"). Checked only on the weekly series -- see this task's
# `decisions` entry for why.
_MIN_WEEKLY_BARS = 26

# yfinance's raw column names -> the DataProvider protocol's contract
# (app/data/base.py: "Columns: open, high, low, close, volume").
_COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


class YFinanceProvider(DataProvider):
    """Primary market data source — free, no API key (docs/Analyse.md §9)."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`, full available history.

        Raises:
            TickerNotFoundError: yfinance returned no data at all for `ticker`.
            DataProviderUnavailableError: yfinance itself failed (rate limit,
                network error, unexpected response).
        """
        return self._fetch(ticker, interval="1d")

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`, using yfinance's native weekly
        interval (``interval="1wk"``) rather than a manual resample of daily
        bars (docs/Analyse.md §9).

        Raises:
            TickerNotFoundError: yfinance returned no data at all for `ticker`.
            InsufficientHistoryError: fewer than `_MIN_WEEKLY_BARS` weekly bars
                are available (e.g. a recent IPO).
            DataProviderUnavailableError: yfinance itself failed (rate limit,
                network error, unexpected response).
        """
        df = self._fetch(ticker, interval="1wk")
        if len(df) < _MIN_WEEKLY_BARS:
            raise InsufficientHistoryError(ticker, available=len(df), required=_MIN_WEEKLY_BARS)
        return df

    def _fetch(self, ticker: str, *, interval: str) -> pd.DataFrame:
        """Fetch and normalize one interval's worth of bars for `ticker`.

        Requests the full available history (``period="max"``): the
        `DataProvider` protocol takes no date-range argument, so trimming to
        whatever window a caller actually wants (the API's `range` query
        param, the SQLite cache) is that caller's job, not this adapter's.
        """
        try:
            raw = yf.Ticker(ticker).history(period="max", interval=interval)
        except YFRateLimitError as exc:
            raise DataProviderUnavailableError(f"yfinance rate-limited: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - yfinance's own errors are broad/undocumented
            raise DataProviderUnavailableError(f"yfinance request failed: {exc}") from exc

        if raw.empty:
            # yfinance's default (non-raising) mode swallows unknown-ticker,
            # delisted-ticker, and "no price data for this range" cases alike
            # into a silently-returned empty DataFrame — this is the one
            # signal available to distinguish "no such ticker" without
            # depending on yfinance's internal logging/exception details.
            raise TickerNotFoundError(ticker)

        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.index.name = "date"
        return df
