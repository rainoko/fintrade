import pandas as pd


def force_index(close: pd.Series, volume: pd.Series, ema_period: int) -> pd.Series:
    """Force Index = Volume x price change, EMA-smoothed.

    Use ema_period=2 for entry timing, ema_period=13 for trend confirmation
    (docs/Analyse.md §2).
    """
    raise NotImplementedError
