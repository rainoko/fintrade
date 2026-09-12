import pandas as pd


def macd_histogram(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.Series:
    """MACD-Histogram. Drives the Screen 1 tide slope and the Impulse gate (docs/Analyse.md §2-3)."""
    raise NotImplementedError
