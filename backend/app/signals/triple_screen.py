import pandas as pd

from app.indicators.force_index import force_index
from app.indicators.stochastic import stochastic_oscillator

# Stochastic %K thresholds -- pinned by docs/Analyse.md §2: "below 30 = oversold,
# above 70 = overbought".
STOCHASTIC_OVERSOLD = 30.0
STOCHASTIC_OVERBOUGHT = 70.0

# Force Index "spike" detection window/multiplier -- see this task's `decisions` entry
# on docs/tasks/screen2-wave.json for why these values (not pinned by Analyse.md §2/§4).
_FORCE_INDEX_SPIKE_WINDOW = 13
_FORCE_INDEX_SPIKE_STDEV_MULTIPLIER = 1.0


def evaluate_tide(weekly_ohlcv: pd.DataFrame) -> str:
    """Screen 1: 'BULLISH' | 'BEARISH' | 'NEUTRAL'.

    From weekly MACD-Histogram slope + 13/26-week EMA relationship (docs/Analyse.md §2).
    """
    raise NotImplementedError


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
    """
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
