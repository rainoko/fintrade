import pandas as pd

from app.indicators._validation import validate_period


def stochastic_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 5,
    d_period: int = 3,
    smooth: int = 3,
) -> pd.DataFrame:
    """Stochastic %K/%D. Params per docs/Analyse.md §4 (5, 3, 3). Returns a DataFrame with 'k' and 'd' columns.

    This is the "slow" Stochastic Oscillator -- SMA-smoothed throughout, not
    EMA-based like the other indicators in this app (docs/Analyse.md §2/§4
    lists "smoothing 3" as a distinct parameter from %K/%D, which only makes
    sense for the classic fast-%K -> smoothed-%K -> %D construction):

    - Fast %K (raw) for bar t = 100 * (close_t - LL) / (HH - LL), where HH/LL
      are the highest high / lowest low over the trailing ``k_period`` bars
      (inclusive of bar t).
    - %K (the "slow", smoothed %K actually used for signals) = simple moving
      average of fast %K over ``smooth`` bars.
    - %D = simple moving average of %K over ``d_period`` bars.

    All three windows use ``pandas.Series.rolling`` (simple/arithmetic
    moving average), not ``ewm`` -- unlike EMA/MACD/Force Index elsewhere in
    this app, which are intentionally exponentially smoothed instead.

    The first ``k_period - 1`` bars have no full HH/LL window and are NaN;
    %K is additionally NaN for another ``smooth - 1`` bars, and %D for a
    further ``d_period - 1`` bars on top of that (standard rolling-window
    warm-up, propagated the way ``pandas.Series.rolling`` already handles
    it -- no custom seeding is needed here the way EMA needs one).

    A bar where the trailing range is flat (``HH == LL``, so the true range
    over the window is zero) leaves fast %K undefined (0/0) rather than
    dividing by zero; pandas/numpy already yields ``NaN`` for that case, so
    no special-casing is required beyond letting the division run.

    Raises:
        TypeError: if ``k_period``, ``d_period``, or ``smooth`` is not an
            ``int`` (e.g. a ``bool`` or a ``float`` like ``5.5``).
        ValueError: if any of ``k_period``, ``d_period``, ``smooth`` is not
            >= 1, or if ``high``, ``low``, ``close`` are not aligned on the
            same index (mirrors ``app.indicators.force_index.force_index``'s
            guard against silent pandas label-based misalignment).
    """
    validate_period("k_period", k_period)
    validate_period("d_period", d_period)
    validate_period("smooth", smooth)

    if not (high.index.equals(low.index) and high.index.equals(close.index)):
        raise ValueError("high, low, and close must share the same index")

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    fast_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    k = fast_k.rolling(window=smooth).mean()
    d = k.rolling(window=d_period).mean()

    return pd.DataFrame({"k": k, "d": d})
