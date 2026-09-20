from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

import pandas as pd

# The one currently-defined reason `ExtendedData` can be "unavailable" rather than a real
# (if empty/null) result -- the fallback (Stooq) provider has no equivalent to yfinance's
# calendar/info/insider_transactions data at all (docs/tasks/backend-market-data-extra-fields.json's
# `decisions` entry). A `Literal` rather than a plain `str` so a future second reason (if one is
# ever needed) is a typed addition here, not a free-text convention callers have to discover.
UnavailableReason = Literal["fallback_provider_active"]


@dataclass(frozen=True)
class InsiderTransaction:
    """One officer/director buy or sell filing (`Ticker.insider_transactions`, Elder ch. 37,
    docs/ideas.md). `transaction_text` is yfinance's own free-text description (e.g. "Sale at
    price 150.00 - 152.00 per share") kept raw rather than parsed into a buy/sell enum -- see
    this task's `decisions` entry for why classifying it is left to a consumer/future task.
    """

    insider: str | None
    position: str | None
    transaction_text: str
    shares: float | None
    value: float | None
    start_date: date | None
    ownership: str | None


@dataclass(frozen=True)
class ExtendedData:
    """Earnings/dividend dates, short interest, and recent insider transactions for one ticker
    (docs/ideas.md; Elder ch. 37/53/58) -- confirmed-live-in-yfinance fields this app didn't
    previously expose (see this task's own `description`).

    Unlike `get_daily_ohlcv`/`get_weekly_ohlcv`, a provider with no equivalent data source
    (`StooqProvider`) doesn't raise for this method -- it returns every field null/empty with
    `unavailable_reason` set, so a caller can distinguish "not checked, this provider doesn't
    support it" from "checked, nothing found" (both would otherwise look identical as a bare
    `None`). See this task's `decisions` entry.
    """

    earnings_date: date | None
    ex_dividend_date: date | None
    shares_short: int | None
    short_ratio: float | None
    short_percent_of_float: float | None
    float_shares: int | None
    insider_transactions: list[InsiderTransaction] = field(default_factory=list)
    unavailable_reason: UnavailableReason | None = None


class DataProvider(Protocol):
    """Common interface for market data sources (docs/architecture/Backend.md §2).

    Implementations must be interchangeable: the yfinance and Stooq adapters both
    satisfy this protocol so the rest of the app never depends on a specific
    provider, and both are mockable behind this same interface in tests.
    """

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`. Columns: open, high, low, close, volume; indexed by date.

        Rows must be ordered oldest-first (most recent row last) -- callers such as
        ``app.portfolio.risk.protective_stop`` rely on this via ``.tail()`` to select the
        most recent trading days. A future implementation of this protocol must preserve
        that ordering.
        """
        ...

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`, same column shape as get_daily_ohlcv."""
        ...

    def get_extended_data(self, ticker: str) -> ExtendedData:
        """Earnings/dividend dates, short interest, and recent insider transactions for
        `ticker` (see `ExtendedData`'s own docstring). Every implementation must return a
        result rather than raise for "this provider has no such data" -- only a genuine
        per-request availability failure (network/rate-limit) should raise
        `app.data.exceptions.DataProviderUnavailableError`.
        """
        ...
