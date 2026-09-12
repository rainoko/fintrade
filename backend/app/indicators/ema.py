import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average. Periods used in this app: 13, 26 (docs/Analyse.md §4).

    Uses the standard recursive EMA definition with smoothing factor
    ``k = 2 / (period + 1)``: seeded with the first value in ``series``, then
    ``EMA_t = close_t * k + EMA_{t-1} * (1 - k)`` for every subsequent point.
    Equivalent to ``series.ewm(span=period, adjust=False).mean()``.

    Consumed by MACD-Histogram, the Impulse gate, Elder-Ray, and the
    Autoenvelope channel (all keyed off EMA(13) and/or EMA(26)).
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    return series.ewm(span=period, adjust=False).mean()
