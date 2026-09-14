import pandas as pd

from app.indicators.ema import ema


def autoenvelope(
    close: pd.Series, ema_period: int = 13, deviation_lookback: int = 100
) -> pd.DataFrame:
    """Moving-average envelope (upper/lower bands) around EMA(13), used for
    profit-target zones and overextension detection (docs/Analyse.md §4: "EMA
    13 ± avg % deviation").

    ``mid`` is ``EMA(close, ema_period)`` (delegates to ``app.indicators.ema``,
    which validates ``ema_period`` and applies the app-wide first-value-seed
    recursive EMA convention). The channel half-width at each bar is the
    trailing rolling average, over the last ``deviation_lookback`` bars, of
    that bar's absolute percentage deviation from ``mid``:
    ``avg_pct_t = mean(|close_i - mid_i| / mid_i for i in [t - lookback + 1, t])``.
    Bands are then a multiplicative envelope: ``upper = mid * (1 + avg_pct)``,
    ``lower = mid * (1 - avg_pct)``. See the decision recorded on
    ``docs/tasks/indicator-autoenvelope.json`` for why this specific
    lookback/rolling/symmetric-band formula was chosen over the alternatives
    considered.

    Returns a DataFrame (same index as ``close``) with 'mid', 'upper', 'lower'
    columns. The first ``deviation_lookback - 1`` bars have a defined 'mid'
    but NaN 'upper'/'lower', since the rolling average deviation isn't yet
    defined over a full window.

    Raises:
        TypeError: if ``ema_period`` or ``deviation_lookback`` is not an
            ``int`` (including ``bool``, a subclass of ``int`` in Python).
        ValueError: if ``ema_period`` or ``deviation_lookback`` is not >= 1.
    """
    if isinstance(deviation_lookback, bool) or not isinstance(deviation_lookback, int):
        raise TypeError(
            f"deviation_lookback must be an int, got {type(deviation_lookback).__name__}"
        )
    if deviation_lookback < 1:
        raise ValueError("deviation_lookback must be >= 1")

    mid = ema(close, ema_period)
    pct_deviation = (close - mid).abs() / mid
    avg_pct_deviation = pct_deviation.rolling(
        window=deviation_lookback, min_periods=deviation_lookback
    ).mean()

    upper = mid * (1 + avg_pct_deviation)
    lower = mid * (1 - avg_pct_deviation)

    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})
