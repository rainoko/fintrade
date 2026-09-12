import pandas as pd

from app.indicators.ema import ema
from app.indicators.macd import macd_histogram


def _direction(series: pd.Series) -> str:
    """'rising' | 'falling', from the last two points of ``series``.

    Unlike Screen 1's tide slope (``app.signals.triple_screen._macd_histogram_slope``,
    which adds a price-normalized "flat" middle threshold because a multi-week tide call
    needs to filter noise around near-zero moves), the Impulse System colors each bar from
    a plain bar-over-bar direction test per docs/Analyse.md §3 -- there's no "flat" state
    in the GREEN/RED/BLUE framing, only "rising" or "falling" for each of the two inputs,
    with disagreement between them (not an internal flat state) producing BLUE. See this
    task's `decisions` entry on docs/tasks/impulse-system.json for the full rationale,
    including the no-change (latest == previous) boundary call.
    """
    latest, previous = series.iloc[-1], series.iloc[-2]
    return "rising" if latest > previous else "falling"


def evaluate_impulse(daily_ohlcv: pd.DataFrame) -> str:
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
    """
    if len(daily_ohlcv) < 2:
        return "BLUE"

    daily_close = daily_ohlcv["close"]
    ema_direction = _direction(ema(daily_close, 13))
    histogram_direction = _direction(macd_histogram(daily_close))

    if ema_direction == "rising" and histogram_direction == "rising":
        return "GREEN"
    if ema_direction == "falling" and histogram_direction == "falling":
        return "RED"
    return "BLUE"
