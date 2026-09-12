import pandas as pd


def force_index(close: pd.Series, volume: pd.Series, ema_period: int) -> pd.Series:
    """Force Index = Volume x price change, EMA-smoothed.

    Raw Force Index for bar t is ``volume_t * (close_t - close_{t-1})``
    (docs/Analyse.md §2); the first bar has no prior close, so its raw value
    is undefined (NaN). The raw series is then smoothed with an EMA using the
    same recursive definition as ``app.indicators.ema`` (k = 2 / (ema_period + 1),
    seeded with the first non-NaN raw value): ``raw.ewm(span=ema_period,
    adjust=False).mean()``, which skips a leading NaN and seeds from the first
    real observation rather than propagating NaN forever.

    Use ema_period=2 for entry timing, ema_period=13 for trend confirmation
    (docs/Analyse.md §2/§4).
    """
    if ema_period < 1:
        raise ValueError("ema_period must be >= 1")
    if len(close) != len(volume):
        raise ValueError("close and volume must be the same length")

    raw = volume * close.diff()
    return raw.ewm(span=ema_period, adjust=False).mean()
