import pandas as pd


def stochastic_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 5,
    d_period: int = 3,
    smooth: int = 3,
) -> pd.DataFrame:
    """Stochastic %K/%D. Params per docs/Analyse.md §4 (5, 3, 3). Returns a DataFrame with 'k' and 'd' columns."""
    raise NotImplementedError
