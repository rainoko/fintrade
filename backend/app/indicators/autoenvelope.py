import pandas as pd

from app.indicators.ema import ema

# Below this magnitude, `mid` is treated as degenerate (e.g. a data-provider
# gap that filled `close`, and therefore `mid`, with 0.0) rather than a real
# EMA(close) value -- see the per-bar pct_deviation guard below.
_MID_ZERO_EPSILON = 1e-9


def autoenvelope(
    close: pd.Series,
    ema_period: int = 13,
    deviation_lookback: int = 100,
    *,
    mid: pd.Series | None = None,
) -> pd.DataFrame:
    """Moving-average envelope (upper/lower bands) around EMA(13), used for
    profit-target zones and overextension detection (docs/Analyse.md §4: "EMA
    13 ± avg % deviation").

    ``mid`` is ``EMA(close, ema_period)`` (delegates to ``app.indicators.ema``,
    which validates ``ema_period`` and applies the app-wide first-value-seed
    recursive EMA convention) -- or, if the caller already computed that exact
    EMA for another purpose, it can be passed in directly via the ``mid``
    keyword instead of being recomputed here (must be index-aligned with
    ``close``, i.e. ``ema(close, ema_period)``'s own output). This lets a
    caller who needs the same EMA(13) elsewhere too (e.g.
    ``app.portfolio.exits.evaluate_exit_flags``, which also feeds it to
    ``protective_stop``/``evaluate_impulse``) share one computation instead of
    each call independently re-deriving an identical EMA pass -- see the
    ``portfolio-exit-rules-followups`` task's `decisions` entry. The channel
    half-width at each bar is the trailing rolling average, over the last
    ``deviation_lookback`` bars, of that bar's absolute percentage deviation
    from ``mid``:
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

    A bar whose ``mid`` is zero or within ``_MID_ZERO_EPSILON`` of it (e.g. a
    data-provider gap that fills ``close``, and therefore ``mid``, with 0.0)
    leaves that bar's percentage deviation undefined (NaN) rather than
    dividing by (near-)zero into +/-inf -- matching how
    ``app.indicators.stochastic.stochastic_oscillator`` leaves a flat
    trailing range's fast %K as NaN (its 0/0 case) instead of raising. Since
    ``avg_pct_deviation``'s rolling window requires every bar in the window
    to be non-NaN (``min_periods`` equals the window size), one degenerate
    bar's NaN deviation propagates into NaN 'upper'/'lower' for exactly the
    following ``deviation_lookback`` bars -- the same bounded, predictable
    NaN warm-up window this function already produces at the start of any
    series, not an unbounded +/-inf leak. ``mid`` itself is left as whatever
    ``app.indicators.ema.ema`` (or the caller-supplied ``mid``) computed,
    degenerate or not -- only the derived deviation quotient is guarded.

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

    if mid is None:
        mid = ema(close, ema_period)
    mid_for_deviation = mid.where(mid.abs() > _MID_ZERO_EPSILON)
    pct_deviation = (close - mid).abs() / mid_for_deviation
    avg_pct_deviation = pct_deviation.rolling(
        window=deviation_lookback, min_periods=deviation_lookback
    ).mean()

    upper = mid * (1 + avg_pct_deviation)
    lower = mid * (1 - avg_pct_deviation)

    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})
