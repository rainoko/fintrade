import pandas as pd

from app.data.base import DataProvider


class CachedDataProvider(DataProvider):
    """Wraps a DataProvider with the SQLite-backed OHLCV cache (docs/architecture/Backend.md §7).

    Avoids re-fetching unchanged history from yfinance/Stooq on every request and
    keeps usage within their free-tier limits.
    """

    def __init__(self, source: DataProvider) -> None:
        self._source = source

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError
