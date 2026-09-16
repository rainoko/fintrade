from typing import Protocol

import pandas as pd


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
