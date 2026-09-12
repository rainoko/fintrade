import pandas as pd


def autoenvelope(close: pd.Series, ema_period: int = 13) -> pd.DataFrame:
    """Moving-average envelope (upper/lower bands), used for profit-target zones (docs/Analyse.md §4).

    Returns a DataFrame with 'mid', 'upper', 'lower' columns.
    """
    raise NotImplementedError
