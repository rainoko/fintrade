import pandas as pd

from app.indicators.ema import ema
from app.indicators.macd import macd_histogram


def _direction(series: pd.Series) -> str:
    """'rising' | 'falling', from the last two points of ``series``.

    The Impulse System colors each bar from a plain, threshold-free bar-over-bar
    comparison per docs/Analyse.md §3 -- the GREEN/RED/BLUE framing only has "rising"
    or "falling" for each of the two inputs (EMA(13), MACD-Histogram), with BLUE
    reserved for disagreement between them, not for a per-indicator "flat" state; §3
    describes no such third per-indicator state to detect, so no noise/flat threshold
    is applied here. A tie (latest == previous) is classified "falling": §3 gives no
    textual basis for favoring either direction on a tie, and treating a
    not-yet-advanced indicator as having failed to demonstrate rising momentum is the
    more conservative read for a gate that can block a fresh BUY. See this task's
    `decisions` entry on docs/tasks/impulse-system.json for the full rationale.
    """
    latest, previous = series.iloc[-1], series.iloc[-2]
    return "rising" if latest > previous else "falling"


def evaluate_impulse(
    daily_ohlcv: pd.DataFrame,
    *,
    ema_13: pd.Series | None = None,
    histogram: pd.Series | None = None,
) -> str:
    """'GREEN' | 'RED' | 'BLUE', from EMA(13) direction + MACD-Histogram direction together (docs/Analyse.md §3).

    Acts as a gate: GREEN blocks fresh SELL signals, RED blocks fresh BUY signals.

    GREEN requires both EMA(13) and the daily MACD-Histogram to be rising bar-over-bar;
    RED requires both falling. Any disagreement between the two -- or fewer than two daily
    bars to even compute a direction -- returns BLUE, matching docs/Analyse.md §3's "any
    action allowed, but signal strength is weaker" description; BLUE is deliberately the
    ambiguous-data fallback too, since (unlike Screen 1's three-way BULLISH/BEARISH/NEUTRAL)
    there is no separate "unknown" state in the GREEN/RED/BLUE vocabulary, and BLUE is the
    one of the three that doesn't gate anything, so insufficient data never masquerades as a
    directional gate. Note: this function only *computes* the Impulse color -- enforcing the
    gate (blocking a fresh BUY under RED, a fresh SELL under GREEN) is signal-engine.py's
    job (docs/architecture/Backend.md §5), not this module's; see this task's `decisions`
    entry for why that's out of scope here.

    ``ema_13``/``histogram``, if given, are used as the already-computed
    ``ema(daily_ohlcv['close'], 13)`` / ``macd_histogram(daily_ohlcv['close'])`` instead of
    recomputing them here (each must be index-aligned with ``daily_ohlcv``). Both are
    independent (a caller may supply either, both, or neither); anything omitted is computed
    internally exactly as before these parameters existed. ``ema_13`` lets a caller who needs
    that same EMA(13) elsewhere too (e.g. ``app.portfolio.exits.evaluate_exit_flags``, which
    also feeds it to ``protective_stop``/``autoenvelope``) share one computation -- see the
    ``portfolio-exit-rules-followups`` task's `decisions` entry. ``histogram`` lets
    ``app.signals.engine.analyse`` share this same EMA(13)/MACD-Histogram pair with the
    ``indicators`` response it builds separately from this gate's color, instead of
    recomputing both a second time on the same ``daily_close`` -- see this task's `decisions`
    entry.
    """
    if len(daily_ohlcv) < 2:
        return "BLUE"

    daily_close = daily_ohlcv["close"]
    if ema_13 is None:
        ema_13 = ema(daily_close, 13)
    if histogram is None:
        histogram = macd_histogram(daily_close)
    ema_direction = _direction(ema_13)
    histogram_direction = _direction(histogram)

    if ema_direction == "rising" and histogram_direction == "rising":
        return "GREEN"
    if ema_direction == "falling" and histogram_direction == "falling":
        return "RED"
    return "BLUE"
