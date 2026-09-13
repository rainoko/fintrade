import pandas as pd

from app.indicators.ema import ema
from app.indicators.force_index import force_index
from app.indicators.macd import macd_histogram
from app.indicators.stochastic import stochastic_oscillator

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

# Stochastic %K thresholds -- pinned by docs/Analyse.md §2: "below 30 = oversold,
# above 70 = overbought".
STOCHASTIC_OVERSOLD = 30.0
STOCHASTIC_OVERBOUGHT = 70.0

# Force Index "spike" detection window/multiplier -- see this task's `decisions` entry
# on docs/tasks/screen2-wave.json for why these values (not pinned by Analyse.md §2/§4).
_FORCE_INDEX_SPIKE_WINDOW = 13
_FORCE_INDEX_SPIKE_STDEV_MULTIPLIER = 1.0


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


def _is_force_index_spike(force_index_2ema: pd.Series, *, negative: bool) -> bool:
    """True if the latest 2-EMA Force Index value is a directional "spike".

    docs/Analyse.md §2/§4 says a negative Force Index spike in an uptrend (or a positive
    one in a downtrend) is the Screen 2 buy/sell cue, but gives no numeric definition of
    "spike" -- see this task's `decisions` entry on docs/tasks/screen2-wave.json for the
    chosen definition: the latest value must (a) have the requested sign, and (b) exceed
    one standard deviation of the trailing `_FORCE_INDEX_SPIKE_WINDOW`-bar Force Index
    magnitude, i.e. be a statistically outsized move relative to this stock's own recent
    volume-weighted momentum, not merely any negative/positive tick.

    Returns False (not a spike) if there isn't enough history yet to compute the rolling
    standard deviation, or if that standard deviation is zero (a perfectly flat recent
    Force Index, where any nonzero value would trivially count as "outsized").
    """
    latest = force_index_2ema.iloc[-1]
    if pd.isna(latest):
        return False
    if negative and latest >= 0:
        return False
    if not negative and latest <= 0:
        return False

    rolling_std = force_index_2ema.rolling(window=_FORCE_INDEX_SPIKE_WINDOW).std().iloc[-1]
    if pd.isna(rolling_std) or rolling_std == 0:
        return False

    return bool(abs(latest) > _FORCE_INDEX_SPIKE_STDEV_MULTIPLIER * rolling_std)


def evaluate_wave(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 2: oscillator state evaluated against the tide direction (docs/Analyse.md §2).

    Computes the daily Stochastic Oscillator (%K 5, %D 3, smoothing 3) and the 2-period-EMA
    Force Index, then classifies the latest bar as one of:

    - ``"OVERSOLD_PULLBACK"``: ``tide == "BULLISH"``, %K is oversold (< 30), and the 2-EMA
      Force Index is a negative spike -- a pullback within an uptrend, i.e. a potential buy
      setup (docs/Analyse.md §2).
    - ``"OVERBOUGHT_RALLY"``: ``tide == "BEARISH"``, %K is overbought (> 70), and the 2-EMA
      Force Index is a positive spike -- a rally within a downtrend, i.e. a potential
      sell/short setup.
    - ``"NO_WAVE"``: any other combination -- ``tide == "NEUTRAL"``, a directional tide
      without a matching oscillator extreme, an oscillator extreme without a matching
      Force Index spike, or not yet enough history for %K/Force Index to be defined (NaN).
      Both the Stochastic and Force Index conditions are required together per
      docs/Analyse.md §2's "oversold Stochastic + negative Force Index spike" framing --
      neither oscillator alone is treated as a signal in isolation (see the
      `verify-elder-signal` skill's Screen 2 checklist item).

    Returns a dict shaped ``{"stochastic_k": float, "force_index_2ema": float, "state": str}``
    per docs/architecture/API.md's ``screens.wave`` response shape. ``stochastic_k`` and
    ``force_index_2ema`` are the latest bar's raw indicator values (which may be NaN if
    ``daily_ohlcv`` doesn't yet have enough history for the rolling/EMA warm-up -- see
    ``app.indicators.stochastic.stochastic_oscillator`` and
    ``app.indicators.force_index.force_index``); NaN indicator values always classify as
    ``"NO_WAVE"`` rather than a guessed direction.

    An empty (0-row) ``daily_ohlcv`` degrades to the same NaN/``"NO_WAVE"`` shape rather than
    raising, mirroring ``evaluate_impulse``'s ``len(daily_ohlcv) < 2`` guard in this same
    module (app/signals/impulse.py) for the analogous reason: there's no bar to read
    ``.iloc[-1]`` from, so this is a data-availability case, not a signal to compute.
    """
    if len(daily_ohlcv) == 0:
        return {
            "stochastic_k": float("nan"),
            "force_index_2ema": float("nan"),
            "state": "NO_WAVE",
        }

    stochastic = stochastic_oscillator(daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"])
    force_index_2ema = force_index(daily_ohlcv["close"], daily_ohlcv["volume"], ema_period=2)

    stochastic_k = stochastic["k"].iloc[-1]
    force_index_latest = force_index_2ema.iloc[-1]

    state = "NO_WAVE"
    if not pd.isna(stochastic_k):
        if (
            tide == "BULLISH"
            and stochastic_k < STOCHASTIC_OVERSOLD
            and _is_force_index_spike(force_index_2ema, negative=True)
        ):
            state = "OVERSOLD_PULLBACK"
        elif (
            tide == "BEARISH"
            and stochastic_k > STOCHASTIC_OVERBOUGHT
            and _is_force_index_spike(force_index_2ema, negative=False)
        ):
            state = "OVERBOUGHT_RALLY"

    return {
        "stochastic_k": float(stochastic_k),
        "force_index_2ema": float(force_index_latest),
        "state": state,
    }


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> bool:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2)."""
    raise NotImplementedError
