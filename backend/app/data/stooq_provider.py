import pandas as pd

from app.data.base import DataProvider


class StooqProvider(DataProvider):
    """Fallback market data source, used when the yfinance provider fails or rate-limits (docs/Analyse.md §9)."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError
