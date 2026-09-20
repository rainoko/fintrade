import pandas as pd

from app.indicators._validation import validate_period


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range (Elder ch. 24, docs/Analyse.md §4): ``max(high - low, |high - prev_close|,
    |low - prev_close|)`` -- the widest of today's own high-low range and either wick's
    distance from yesterday's close, capturing the extra range a gap (up or down) adds on top
    of the plain high-low span.

    The first bar has no prior close to compare against, so its True Range is undefined
    (NaN) -- the same "no prior bar -> NaN" warm-up convention every other diff-based
    indicator in this app uses (e.g. ``app.indicators.force_index.force_index``'s first raw
    value, ``app.indicators.rsi.rsi``'s first ``close.diff()``).

    This is also exactly what ``app.indicators.atr.atr`` and
    ``app.indicators.directional_system``'s ``+DM``/``-DM``-derived ``+DI``/``-DI`` need, per
    docs/ideas.md's own note that "this is also exactly what Average True Range needs, so the
    two should share one implementation" -- both call this function rather than each
    re-deriving their own copy.

    Raises:
        ValueError: if ``high``, ``low``, and ``close`` are not aligned on the same index
            (mirrors ``app.indicators.stochastic.stochastic_oscillator``'s equivalent guard
            against silent pandas label-based misalignment).
    """
    if not (high.index.equals(low.index) and high.index.equals(close.index)):
        raise ValueError("high, low, and close must share the same index")

    prev_close = close.shift(1)
    high_low = high - low
    high_prev_close = (high - prev_close).abs()
    low_prev_close = (low - prev_close).abs()

    # `skipna=False`: the first bar's `high_prev_close`/`low_prev_close` are NaN (no prior
    # close), but `high_low` alone is always defined -- pandas' default `max(..., skipna=True)`
    # would silently ignore those two NaNs and fall back to the always-defined `high_low`
    # value instead of propagating "undefined" for this bar, which is the wrong answer (True
    # Range genuinely has no defined value without a prior close to compare against).
    return pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1, skipna=False)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 13) -> pd.Series:
    """Average True Range (Elder ch. 24, docs/Analyse.md §4) -- the trailing ``period``-day
    simple/arithmetic average of ``true_range``, 13 days by default (the book's own default,
    docs/ideas.md).

    A plain ``.rolling(window=period).mean()`` is used, not Wilder's smoothed moving average
    (an EMA-like running average with smoothing constant ``1/period``) -- consistent with this
    app's existing ``app.indicators.rsi.rsi`` decision (docs/tasks/backend-indicator-rsi.json)
    to prefer a plain average over Wilder's variant for the same two reasons: the book's own
    "N-day average" phrasing (docs/ideas.md) reads as a plain average with no mention of
    exponential smoothing, and a simple rolling mean keeps a hand-computed reference-value
    test tractable without an additional smoothing-seed convention to also hand-verify. See
    this task's `decisions` entry (docs/tasks/backend-indicator-atr-adx.json).

    Absolute level is meaningful here (unlike a cumulative series such as
    ``app.indicators.obv.obv``) -- it's directly usable, per docs/ideas.md's own numeric usage
    rules, as an entry-depth reference (pullbacks tend to bottom near -1 ATR from the EMA), a
    stop-distance floor (>= 1 ATR from entry), and profit-target spacing (+1/+2/+3 ATR) --
    none of which this task wires up (computation + exposure only, see this task's own scope
    note).

    The first ``period`` bars are NaN: ``true_range``'s own first bar is already NaN (no prior
    close), so a full ``period``-bar rolling window isn't available until bar index ``period``
    (0-indexed) -- one bar later than a rolling average over a series with no leading NaN of
    its own would need.

    Raises:
        TypeError: if ``period`` is not an ``int`` (e.g. a ``bool`` or a ``float`` like
            ``13.5``).
        ValueError: if ``period`` is not >= 1, or if ``high``, ``low``, ``close`` are not
            aligned on the same index (see ``true_range``).
    """
    validate_period("period", period)

    return true_range(high, low, close).rolling(window=period).mean()
