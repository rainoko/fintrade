import pandas as pd

from app.data.base import DataProvider


class YFinanceProvider(DataProvider):
    """Primary market data source — free, no API key (docs/Analyse.md §9)."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError
