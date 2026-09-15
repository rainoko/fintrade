import pandas as pd


def bull_power(high: pd.Series, ema_13: pd.Series) -> pd.Series:
    """Bull Power = High - EMA(13) (docs/Analyse.md §4).

    ``ema_13`` is the caller-supplied EMA(13) of the close price (see
    ``app.indicators.ema.ema``) — Elder-Ray does not compute its own EMA, it
    reuses the trend EMA already used for the tide/impulse gate.

    Raises:
        ValueError: if ``high`` and ``ema_13`` are not aligned on the same
            index. ``high - ema_13`` aligns by pandas index *label*, not
            position, so two equal-length Series with offset or otherwise
            different indices would otherwise silently combine into a bogus,
            mis-shifted result instead of raising.
    """
    if not high.index.equals(ema_13.index):
        raise ValueError("high and ema_13 must share the same index")
    return high - ema_13


def bear_power(low: pd.Series, ema_13: pd.Series) -> pd.Series:
    """Bear Power = Low - EMA(13) (docs/Analyse.md §4).

    ``ema_13`` is the caller-supplied EMA(13) of the close price (see
    ``app.indicators.ema.ema``) — Elder-Ray does not compute its own EMA, it
    reuses the trend EMA already used for the tide/impulse gate.

    Raises:
        ValueError: if ``low`` and ``ema_13`` are not aligned on the same
            index. ``low - ema_13`` aligns by pandas index *label*, not
            position, so two equal-length Series with offset or otherwise
            different indices would otherwise silently combine into a bogus,
            mis-shifted result instead of raising.
    """
    if not low.index.equals(ema_13.index):
        raise ValueError("low and ema_13 must share the same index")
    return low - ema_13
