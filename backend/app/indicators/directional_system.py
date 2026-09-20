import pandas as pd

from app.indicators._validation import validate_period
from app.indicators.atr import true_range


def plus_minus_dm(high: pd.Series, low: pd.Series) -> tuple[pd.Series, pd.Series]:
    """+DM/-DM (Directional Movement, Elder ch. 24, docs/Analyse.md §4) -- the portion of
    today's high-low range that extends beyond yesterday's, signed by direction:

    - ``up_move`` = ``high - prior high``; ``down_move`` = ``prior low - low``.
    - ``+DM`` = ``up_move`` if ``up_move > down_move`` AND ``up_move > 0``, else 0.
    - ``-DM`` = ``down_move`` if ``down_move > up_move`` AND ``down_move > 0``, else 0.

    This is Wilder's original, standard Directional Movement definition (the only reading of
    docs/ideas.md's "the portion of today's high-low range that extends beyond yesterday's,
    signed by direction" that's actually fully specified) -- an "inside day" (today's whole
    range within yesterday's), a pure gap with no net extension either way, or a tie (up_move
    == down_move, both positive) all yield ``+DM = -DM = 0``: never both directions counted at
    once, and never counted at all unless one direction's extension strictly exceeds the
    other's.

    The first bar has no prior high/low to compare against, so both are NaN there -- forced
    explicitly (rather than left to fall out of the ``>``-against-NaN comparisons below, which
    would otherwise evaluate to ``False`` and silently produce ``0.0`` instead of "undefined")
    since ``0`` is a real, meaningful value here (no directional movement) that must stay
    distinguishable from "not yet computable."

    Returns ``(plus_dm, minus_dm)``, same index as ``high``/``low``.

    Raises:
        ValueError: if ``high`` and ``low`` are not aligned on the same index.
    """
    if not high.index.equals(low.index):
        raise ValueError("high and low must share the same index")

    up_move = high.diff()
    down_move = low.shift(1) - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    if len(high) > 0:
        plus_dm.iloc[0] = float("nan")
        minus_dm.iloc[0] = float("nan")

    return plus_dm, minus_dm


def plus_minus_di(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 13
) -> tuple[pd.Series, pd.Series]:
    """+DI/-DI (Directional Indicators, Elder ch. 24, docs/Analyse.md §4) -- ``+DM``/``-DM``
    (``plus_minus_dm``) each smoothed over ``period`` days (13 by default, matching
    ``app.indicators.atr.atr``'s own default) and expressed as a percentage of similarly
    smoothed True Range (``app.indicators.atr.true_range``): ``+DI = 100 * smoothed(+DM) /
    smoothed(TR)``, ``-DI`` mirrored. Always >= 0 (both the numerator and denominator are
    themselves always >= 0).

    "Smoothed" here is a plain ``.rolling(window=period).mean()`` on ``+DM``/``-DM``/``TR``
    each independently, then the ratio taken -- not Wilder's smoothed moving average, and not
    a rolling mean of the ``DM/TR`` ratio series itself (docs/ideas.md's own "smoothed(DM/TR)"
    phrasing is ambiguous between the two; smoothing numerator and denominator independently
    before dividing is the standard, textbook Directional System construction, and keeps this
    consistent with ``app.indicators.atr.atr``'s own plain-rolling-mean choice for the same
    "N-day average" defaults elsewhere in this module). See this task's `decisions` entry
    (docs/tasks/backend-indicator-atr-adx.json).

    Both are NaN for as long as either the underlying ``+DM``/``-DM`` warm-up (first bar) or
    the ``period``-bar rolling window hasn't filled -- i.e. the same first ``period`` bars
    ``app.indicators.atr.atr`` is NaN for, given the same ``period``.

    A trailing window with zero smoothed True Range (a perfectly flat market, high == low ==
    prior close for every bar in the window) leaves both ``+DI``/``-DI`` as a 0/0 (NaN) or a
    finite-over-zero (+/-inf) division rather than a raised error -- pandas/numpy already
    yields those results for free, matching how ``app.indicators.stochastic
    .stochastic_oscillator`` leaves a flat trailing range's %K undefined instead of
    special-casing it.

    Returns ``(plus_di, minus_di)``, same index as ``high``/``low``/``close``.

    Raises:
        TypeError: if ``period`` is not an ``int`` (e.g. a ``bool`` or a ``float`` like
            ``13.5``).
        ValueError: if ``period`` is not >= 1, or if ``high``, ``low``, ``close`` are not
            aligned on the same index (see ``plus_minus_dm``/``true_range``).
    """
    validate_period("period", period)

    plus_dm, minus_dm = plus_minus_dm(high, low)
    tr = true_range(high, low, close)

    smoothed_plus_dm = plus_dm.rolling(window=period).mean()
    smoothed_minus_dm = minus_dm.rolling(window=period).mean()
    smoothed_tr = tr.rolling(window=period).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr

    return plus_di, minus_di


def dx(plus_di: pd.Series, minus_di: pd.Series) -> pd.Series:
    """DX (Directional Movement Index, Elder ch. 24, docs/Analyse.md §4): ``100 * |+DI - -DI|
    / (+DI + -DI)`` -- how lopsided today's directional balance is, 0 (perfectly balanced) to
    100 (one direction entirely dominant), before ``adx`` smooths it into a trend-strength
    reading.

    Takes already-computed ``+DI``/``-DI`` (``plus_minus_di``) rather than raw OHLC, so a
    caller sharing one ``+DI``/``-DI`` pass across multiple derived values (this module's own
    ``adx``, or a future per-bar precompute-and-slice caller mirroring
    ``app.signals.engine.analyse_history``'s existing pattern for ``rsi``/``channel_upper``)
    doesn't need to recompute them.

    A trailing bar where both ``+DI`` and ``-DI`` are 0 (no directional movement at all, e.g.
    a perfectly flat market) is a 0/0 division, left as NaN rather than special-cased --
    matching ``plus_minus_di``'s own zero-True-Range convention.

    Raises:
        ValueError: if ``plus_di`` and ``minus_di`` are not aligned on the same index.
    """
    if not plus_di.index.equals(minus_di.index):
        raise ValueError("plus_di and minus_di must share the same index")

    return 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)


def adx(plus_di: pd.Series, minus_di: pd.Series, period: int = 13) -> pd.Series:
    """ADX (Average Directional Index, Elder ch. 24, docs/Analyse.md §4) -- ``dx`` smoothed
    over a trailing ``period``-day simple/arithmetic average (13 by default, matching
    ``app.indicators.atr.atr``/``plus_minus_di``'s own default), turning the noisy bar-by-bar
    ``DX`` reading into Elder's actual trend-strength/new-trend-detection signal.

    Same plain ``.rolling(window=period).mean()`` choice as ``app.indicators.atr.atr`` and
    ``plus_minus_di``, not Wilder's smoothed moving average -- see ``plus_minus_di``'s own
    docstring and this task's `decisions` entry for why.

    Elder's own usage rules for the *value* this produces (docs/ideas.md) -- trade
    trend-following only while ADX is rising, an ADX rise of 4 steps from its own low point
    (e.g. 9 -> 13) "rings a bell" on a new trend being born, a downturn from above both DI
    lines is a take-partial-profits cue -- are explicitly out of scope for this task
    (computation + exposure only; see this task's own scope note) and are not evaluated here.

    NaN until ``period`` further bars of valid ``dx`` are available on top of ``plus_di``/
    ``minus_di``'s own warm-up -- i.e. a longer warm-up than ``+DI``/``-DI``/``atr`` (twice
    ``period`` bars, roughly, rather than one ``period``-bar window).

    Raises:
        TypeError: if ``period`` is not an ``int`` (e.g. a ``bool`` or a ``float`` like
            ``13.5``).
        ValueError: if ``period`` is not >= 1, or if ``plus_di`` and ``minus_di`` are not
            aligned on the same index (see ``dx``).
    """
    validate_period("period", period)

    return dx(plus_di, minus_di).rolling(window=period).mean()
