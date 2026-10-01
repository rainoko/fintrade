"""Ticker-keyed `DataProvider` adapter over `IBKRProvider` (app/data/ibkr_provider.py),
built for `backend-ibkr-primary-data-provider`: when the IBKR Client Portal Gateway is
connected/authenticated, `app.api.dependencies.get_data_provider` uses `IBKRDataProvider`
(via `IBKRPrimaryDataProvider` below) as the app's primary market-data source instead of
yfinance/Stooq -- see that task's `decisions` entry for the full reversal rationale (also
recorded on `app.data.ibkr_provider`'s own module docstring, which this reverses).

Two distinct classes, not one, because they solve two different problems:

- `IBKRDataProvider` is the thin, purely mechanical ticker->conid->bars translation
  (`IBKRProvider` itself is conid-keyed, not ticker-keyed, and deliberately stays that
  way -- see its own module docstring). It has no opinion about extended data (earnings/
  dividend dates, short interest, insider transactions) beyond "I can't provide it" --
  this task's checklist item 1 live-gateway research confirmed IBKR's Client Portal Web
  API has no equivalent to yfinance's `calendar`/`info`/`insider_transactions` fields (see
  this task's `decisions` entry for exactly what was probed and found unavailable).
- `IBKRPrimaryDataProvider` is the composition `app.api.dependencies` actually wires up:
  OHLCV from an `IBKRDataProvider` (through the existing SQLite `CachedDataProvider`, with
  itself as both primary *and* fallback -- see that class's own docstring for why that's
  deliberate, not an oversight), extended data delegated whole-sale to a separate,
  still-cached yfinance/Stooq `DataProvider` -- the permanent, structural carve-out this
  task's `decisions` entry records, not a per-call resilience fallback (which the task's
  own description explicitly rules out while IBKR is connected).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import pandas as pd

from app.data.base import DataProvider, ExtendedData
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.ibkr_provider import IBKRBar, IBKRProvider, IBKRUnavailableError

_T = TypeVar("_T")

# Mirrors YFinanceProvider/StooqProvider's own _MIN_WEEKLY_BARS (Analyse.md §8: Screen 1
# needs 26 weeks of history to seed its 26-week EMA) -- kept as a local constant (not
# imported) since none of these provider modules otherwise depend on each other (see
# app.data.fixture_provider's identical precedent).
_MIN_WEEKLY_BARS = 26

_COLUMNS = ("open", "high", "low", "close", "volume")


class IBKRDataProvider(DataProvider):
    """`DataProvider`-protocol adapter over `IBKRProvider`: resolves `ticker` to an IBKR
    conid (`IBKRProvider.resolve_conid`, itself cached -- see that method's own docstring)
    then fetches bars for that conid (`get_daily_bars`/`get_weekly_bars`).

    `get_extended_data` always returns an "unavailable" result (never raises) -- this
    class alone has no extended-data source at all; `IBKRPrimaryDataProvider` below is
    what actually routes extended-data requests to a real source (yfinance/Stooq). This
    method exists mainly for protocol completeness / defensive direct use -- the normal
    `app.api.dependencies.get_data_provider` wiring never calls it, since
    `IBKRPrimaryDataProvider.get_extended_data` bypasses this instance entirely.
    """

    def __init__(self, ibkr: IBKRProvider) -> None:
        self._ibkr = ibkr

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`, full available IBKR history (see
        `IBKRProvider.get_daily_bars`'s own docstring for exactly how much that is).

        Raises:
            TickerNotFoundError: `ticker` couldn't be resolved to a conid (unknown to
                IBKR, or ambiguous across more than one distinct listing -- see
                `IBKRProvider.resolve_conid`'s own docstring for why both degrade to the
                same outcome), or IBKR returned no bars at all for a resolved conid.
            DataProviderUnavailableError: the gateway isn't connected, or the request
                itself failed.
        """
        conid = self._resolve_conid_or_raise(ticker)
        bars = self._fetch(lambda: self._ibkr.get_daily_bars(conid))
        if not bars:
            raise TickerNotFoundError(ticker)
        return _bars_to_frame(bars)

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`. Same resolution/error behavior as
        `get_daily_ohlcv`, plus an `InsufficientHistoryError` floor matching
        `YFinanceProvider`/`StooqProvider`'s own `_MIN_WEEKLY_BARS` (Screen 1's 26-week
        minimum, docs/Analyse.md §8) -- `get_daily_ohlcv` has no equivalent floor, mirroring
        those same two providers' own daily/weekly asymmetry.

        Raises:
            TickerNotFoundError: `ticker` couldn't be resolved to a conid, or IBKR
                returned no bars at all for a resolved conid.
            InsufficientHistoryError: fewer than `_MIN_WEEKLY_BARS` weekly bars are
                available (e.g. a recent IPO).
            DataProviderUnavailableError: the gateway isn't connected, or the request
                itself failed.
        """
        conid = self._resolve_conid_or_raise(ticker)
        bars = self._fetch(lambda: self._ibkr.get_weekly_bars(conid))
        if not bars:
            raise TickerNotFoundError(ticker)
        if len(bars) < _MIN_WEEKLY_BARS:
            raise InsufficientHistoryError(ticker, available=len(bars), required=_MIN_WEEKLY_BARS)
        return _bars_to_frame(bars)

    def get_extended_data(self, ticker: str) -> ExtendedData:
        """Always "unavailable" -- see this class's own docstring for why, and
        `IBKRPrimaryDataProvider.get_extended_data` for what actually serves this in the
        real `get_data_provider` wiring.
        """
        return ExtendedData(
            earnings_date=None,
            ex_dividend_date=None,
            shares_short=None,
            short_ratio=None,
            short_percent_of_float=None,
            float_shares=None,
            insider_transactions=[],
            unavailable_reason="fallback_provider_active",
        )

    def _resolve_conid_or_raise(self, ticker: str) -> int:
        conid = self._fetch(lambda: self._ibkr.resolve_conid(ticker))
        if conid is None:
            raise TickerNotFoundError(ticker)
        return conid

    @staticmethod
    def _fetch(call: Callable[[], _T]) -> _T:
        """Runs `call` (a zero-arg callable wrapping one `IBKRProvider` method call),
        translating `IBKRUnavailableError` into the `DataProvider` protocol's own
        `DataProviderUnavailableError` -- callers of this class expect the same exception
        hierarchy `YFinanceProvider`/`StooqProvider` raise (app/data/exceptions.py), not
        this provider's own IBKR-specific exception type.
        """
        try:
            return call()
        except IBKRUnavailableError as exc:
            raise DataProviderUnavailableError(str(exc)) from exc


def _bars_to_frame(bars: list[IBKRBar]) -> pd.DataFrame:
    """`list[IBKRBar]` (oldest-first, per `IBKRProvider.get_daily_bars`/`get_weekly_bars`'s
    own docstrings) -> the `DataProvider` protocol's OHLCV frame shape (app/data/base.py):
    columns open/high/low/close/volume, indexed by date. Strips each bar's UTC tzinfo
    (`YFinanceProvider._normalize`'s identical precedent) rather than normalizing further
    to a bare date -- downstream code (e.g. `app.data.cache.CachedDataProvider._upsert`)
    already tolerates a full-datetime index via `idx.date()`.
    """
    index = pd.DatetimeIndex([pd.Timestamp(bar.timestamp).tz_localize(None) for bar in bars], name="date")
    return pd.DataFrame(
        {
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
            "volume": [bar.volume for bar in bars],
        },
        columns=list(_COLUMNS),
        index=index,
    )


class IBKRPrimaryDataProvider(DataProvider):
    """The actual `DataProvider` `app.api.dependencies.get_data_provider` returns while
    IBKR is connected: daily/weekly OHLCV from `ohlcv_provider` (expected to be a
    `CachedDataProvider` wrapping an `IBKRDataProvider` as *both* its primary and its
    fallback -- see `app.api.dependencies._build_ibkr_primary_data_provider` for why),
    extended data delegated entirely to `extended_data_provider` (expected to be the
    existing cached yfinance/Stooq chain) -- this task's own `decisions` entry records why
    extended data is a permanent, structural carve-out rather than a per-call-failure
    resilience fallback.

    Deliberately takes both already-constructed as plain `DataProvider`s (not an
    `IBKRProvider`/`db` pair it builds itself) so this class stays a pure router with no
    opinion on caching/composition details -- those live where the rest of this app's
    `DataProvider` composition already lives, `app.api.dependencies`.
    """

    def __init__(self, ohlcv_provider: DataProvider, extended_data_provider: DataProvider) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._extended_data_provider = extended_data_provider

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        return self._ohlcv_provider.get_daily_ohlcv(ticker)

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        return self._ohlcv_provider.get_weekly_ohlcv(ticker)

    def get_extended_data(self, ticker: str) -> ExtendedData:
        return self._extended_data_provider.get_extended_data(ticker)
