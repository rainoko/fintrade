import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from app.data.base import DataProvider, ExtendedData, InsiderTransaction
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

    def get_extended_data(self, ticker: str) -> ExtendedData:
        """Earnings/dividend dates (`Ticker.calendar`), short interest (`Ticker.info`), and
        recent insider transactions (`Ticker.insider_transactions`) for `ticker` --
        docs/ideas.md's confirmed-live-in-yfinance fields (Elder ch. 37/53/58).

        Raises:
            DataProviderUnavailableError: yfinance itself failed (rate limit, network error,
                unexpected response) on any of the three underlying calls -- caught as one
                unit since they're all part of the same "extended data" fetch, unlike
                `get_daily_ohlcv`/`get_weekly_ohlcv` which callers fetch independently.

        Individual fields are `None`/empty when yfinance itself succeeded but simply has no
        value for this ticker (e.g. a smaller/thinly-covered company with no reported short
        interest, docs/ideas.md's own "yfinance's own data can be incomplete for smaller
        tickers" caveat) -- distinct from the provider-level failure above, which raises
        rather than returning a half-populated result.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            calendar = yf_ticker.calendar or {}
            info = yf_ticker.info or {}
            insider_df = yf_ticker.insider_transactions
        except YFRateLimitError as exc:
            raise DataProviderUnavailableError(f"yfinance rate-limited: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - yfinance's own errors are broad/undocumented
            raise DataProviderUnavailableError(f"yfinance request failed: {exc}") from exc

        # `Ticker.calendar`'s "Earnings Date" is a list -- Yahoo sometimes reports an
        # unconfirmed 2-day estimate window rather than a single confirmed date -- so the
        # earliest entry is used as the single date this app surfaces (see this task's
        # `decisions` entry for why the window's upper bound isn't also exposed).
        earnings_dates = calendar.get("Earnings Date") or []
        earnings_date = min(earnings_dates) if earnings_dates else None

        return ExtendedData(
            earnings_date=earnings_date,
            ex_dividend_date=calendar.get("Ex-Dividend Date"),
            shares_short=_int_or_none(info.get("sharesShort")),
            short_ratio=_float_or_none(info.get("shortRatio")),
            short_percent_of_float=_float_or_none(info.get("shortPercentOfFloat")),
            float_shares=_int_or_none(info.get("floatShares")),
            insider_transactions=_parse_insider_transactions(insider_df),
        )

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


def _int_or_none(value: int | float | str | None) -> int | None:
    """`Ticker.info` uses plain `None` for a genuinely missing key, but a present-but-NaN
    float for some fields yfinance still populates from an incomplete upstream record --
    both must map to `None` here rather than a Pydantic-rejecting `nan`."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return int(value)


def _float_or_none(value: int | float | str | None) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def _str_or_none(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _parse_insider_transactions(raw: pd.DataFrame | None) -> list[InsiderTransaction]:
    """`Ticker.insider_transactions` columns (yfinance's `Holders._parse_insider_transactions`):
    `Insider`, `Position`, `Transaction`, `Text`, `Shares`, `Value`, `Start Date`, `Ownership`.
    `None`/an empty frame (no filings reported, or yfinance's own request failure swallowed
    internally rather than raised -- see this method's own docstring) both map to `[]`, not an
    error: an empty list is this app's normal "nothing to report" representation, distinct
    from `ExtendedData.unavailable_reason`'s "not supported by this provider at all"."""
    if raw is None or raw.empty:
        return []
    transactions: list[InsiderTransaction] = []
    for _, row in raw.iterrows():
        start_date_raw = row.get("Start Date")
        transactions.append(
            InsiderTransaction(
                insider=_str_or_none(row.get("Insider")),
                position=_str_or_none(row.get("Position")),
                transaction_text=_str_or_none(row.get("Text")) or "",
                shares=_float_or_none(row.get("Shares")),
                value=_float_or_none(row.get("Value")),
                start_date=(
                    start_date_raw.date() if hasattr(start_date_raw, "date") else None
                ),
                ownership=_str_or_none(row.get("Ownership")),
            )
        )
    return transactions
