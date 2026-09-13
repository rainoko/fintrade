import pandas as pd

from app.indicators.ema import ema
from app.indicators.macd import macd_histogram

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


def _macd_histogram_slope(weekly_close: pd.Series) -> str:
    """'rising' | 'falling' | 'flat', from the last two weekly MACD-Histogram points."""
    histogram = macd_histogram(weekly_close)
    latest, previous = histogram.iloc[-1], histogram.iloc[-2]
    latest_close = weekly_close.iloc[-1]

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


def evaluate_tide(weekly_ohlcv: pd.DataFrame) -> str:
    """Screen 1: 'BULLISH' | 'BEARISH' | 'NEUTRAL'.

    From weekly MACD-Histogram slope + 13/26-week EMA relationship (docs/Analyse.md §2).

    BULLISH requires the histogram slope to be rising *and* the 13-week EMA
    above the 26-week EMA; BEARISH requires falling *and* 13-week EMA below
    26-week EMA. Any other combination -- a flat slope, the slope and EMA
    relationship disagreeing, or too little history to compute a slope at
    all -- returns NEUTRAL rather than forcing a guess, per docs/Analyse.md
    §2 and this task's checklist.
    """
    if len(weekly_ohlcv) < 2:
        return "NEUTRAL"

    weekly_close = weekly_ohlcv["close"]
    slope = _macd_histogram_slope(weekly_close)

    ema_13 = ema(weekly_close, 13).iloc[-1]
    ema_26 = ema(weekly_close, 26).iloc[-1]

    if slope == "rising" and ema_13 > ema_26:
        return "BULLISH"
    if slope == "falling" and ema_13 < ema_26:
        return "BEARISH"
    return "NEUTRAL"


def evaluate_wave(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 2: oscillator state evaluated against the tide direction (docs/Analyse.md §2)."""
    raise NotImplementedError


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> bool:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2)."""
    raise NotImplementedError
