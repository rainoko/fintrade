from dataclasses import dataclass

import pandas as pd

from app.indicators.ema import ema
from app.indicators.macd import macd_components

# Screen 1 (Tide): minimum weekly MACD-Histogram step, expressed as a
# fraction of the latest weekly close, required to call the histogram
# "rising" or "falling" rather than "flat" (docs/Analyse.md §2 says tide is
# NEUTRAL "if MACD-H slope is flat/ambiguous" but deliberately leaves the
# flat threshold itself undefined -- see this task's `decisions` entry and
# the indicator-macd-histogram task's own decisions entry, which explicitly
# deferred this choice here). Normalizing by price (rather than a fixed
# absolute dollar step) keeps the threshold meaningful across tickers of
# very different price scales.
_FLAT_SLOPE_THRESHOLD_PCT = 0.001


@dataclass(frozen=True)
class TideResult:
    """Screen 1 output -- mirrors TideScreen (app/api/schemas.py) field-for-field.

    Returning both fields (rather than just the trend string) so a future
    API-wiring task can populate ``TideScreen.trend`` and
    ``TideScreen.weekly_macd_histogram_slope`` directly from one call,
    without reaching across the module boundary for a private helper or
    recomputing the slope independently -- see this task's `decisions` entry.
    """

    trend: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    weekly_macd_histogram_slope: str  # "rising" | "falling" | "flat"


def macd_histogram_slope(histogram: pd.Series, latest_close: float) -> str:
    """'rising' | 'falling' | 'flat', from the last two MACD-Histogram points.

    Public (not module-private) because it's a general "classify this
    histogram's last step" rule, not something intrinsically tied to
    ``evaluate_tide``'s internals -- see this task's `decisions` entry for
    why it was promoted out of ``_macd_histogram_slope``. Takes the already-
    computed histogram (rather than a close-price series) so a caller who
    also needs other MACD components (e.g. ``evaluate_tide`` needing
    EMA(slow) too) can get everything from a single
    ``app.indicators.macd.macd_components`` call instead of computing the
    histogram twice.
    """
    latest, previous = histogram.iloc[-1], histogram.iloc[-2]

    if latest_close == 0:
        # Degenerate case (a zero close price) that never occurs with real
        # market data -- fall back to an absolute-zero comparison instead
        # of dividing by zero.
        step = latest - previous
    else:
        step = (latest - previous) / abs(latest_close)

    if step > _FLAT_SLOPE_THRESHOLD_PCT:
        return "rising"
    if step < -_FLAT_SLOPE_THRESHOLD_PCT:
        return "falling"
    return "flat"


def evaluate_tide(weekly_ohlcv: pd.DataFrame) -> TideResult:
    """Screen 1: trend + the MACD-Histogram slope classification behind it.

    From weekly MACD-Histogram slope + 13/26-week EMA relationship (docs/Analyse.md §2).

    ``trend`` is 'BULLISH' | 'BEARISH' | 'NEUTRAL'. BULLISH requires the
    histogram slope to be rising *and* the 13-week EMA above the 26-week
    EMA; BEARISH requires falling *and* 13-week EMA below 26-week EMA. Any
    other combination -- a flat slope, the slope and EMA relationship
    disagreeing, or too little history to compute a slope at all -- returns
    NEUTRAL rather than forcing a guess, per docs/Analyse.md §2 and this
    task's checklist.

    ``weekly_macd_histogram_slope`` is the raw 'rising' | 'falling' | 'flat'
    classification that fed that decision. Exposing it separately (rather
    than collapsing it into just the trend) lets a downstream consumer such
    as the confidence-scoring component tell apart the two ways a NEUTRAL
    trend can arise -- slope 'flat' (genuinely ambiguous) vs. slope
    'rising'/'falling' but overridden to NEUTRAL by a disagreeing EMA
    relationship (the "mixed" case docs/Analyse.md §6's confidence table
    scores at 50%) -- without recomputing the EMA relationship itself; see
    this task's `decisions` entry.

    Too little history (<2 weekly bars) to compute a slope at all returns
    NEUTRAL/'flat' without calling either indicator.
    """
    if len(weekly_ohlcv) < 2:
        return TideResult(trend="NEUTRAL", weekly_macd_histogram_slope="flat")

    weekly_close = weekly_ohlcv["close"]
    latest_close = weekly_close.iloc[-1]

    components = macd_components(weekly_close)
    slope = macd_histogram_slope(components.histogram, latest_close)

    ema_13 = ema(weekly_close, 13).iloc[-1]
    ema_26 = components.ema_slow.iloc[-1]

    if slope == "rising" and ema_13 > ema_26:
        trend = "BULLISH"
    elif slope == "falling" and ema_13 < ema_26:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return TideResult(trend=trend, weekly_macd_histogram_slope=slope)


def evaluate_wave(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 2: oscillator state evaluated against the tide direction (docs/Analyse.md §2)."""
    raise NotImplementedError


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> bool:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2)."""
    raise NotImplementedError
