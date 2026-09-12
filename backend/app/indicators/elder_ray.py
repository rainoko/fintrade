import pandas as pd


def bull_power(high: pd.Series, ema_13: pd.Series) -> pd.Series:
    """Bull Power = High - EMA(13) (docs/Analyse.md §4)."""
    raise NotImplementedError


def bear_power(low: pd.Series, ema_13: pd.Series) -> pd.Series:
    """Bear Power = Low - EMA(13) (docs/Analyse.md §4)."""
    raise NotImplementedError
