from dataclasses import dataclass

import pandas as pd

from app.indicators.ema import ema
from app.indicators.force_index import force_index
from app.indicators.macd import macd_components
from app.indicators.stochastic import stochastic_oscillator

# Stochastic %K thresholds -- pinned by docs/Analyse.md §2: "below 30 = oversold,
# above 70 = overbought".
STOCHASTIC_OVERSOLD = 30.0
STOCHASTIC_OVERBOUGHT = 70.0

# Force Index "spike" detection window/multiplier -- see this task's `decisions` entry
# on docs/tasks/screen2-wave.json for why these values (not pinned by Analyse.md §2/§4).
_FORCE_INDEX_SPIKE_WINDOW = 13
_FORCE_INDEX_SPIKE_STDEV_MULTIPLIER = 1.0

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

    # Degenerate case (a zero close price) that never occurs with real market
    # data -- fall back to an absolute-zero comparison instead of dividing by zero.
    step = latest - previous if latest_close == 0 else (latest - previous) / abs(latest_close)

    if step > _FLAT_SLOPE_THRESHOLD_PCT:
        return "rising"
    if step < -_FLAT_SLOPE_THRESHOLD_PCT:
        return "falling"
    return "flat"


def validate_weekly_ohlcv_columns(weekly_ohlcv: pd.DataFrame) -> None:
    """Raise if ``weekly_ohlcv`` lacks the ``close`` column ``evaluate_tide`` requires.

    Factored out (mirroring ``app.portfolio.risk.validate_daily_ohlcv_columns``'s equivalent
    role for ``protective_stop``/daily OHLCV) so a caller that needs to touch
    ``weekly_ohlcv``'s columns of its own *before* calling ``evaluate_tide`` (e.g.
    ``app.portfolio.exits.evaluate_exit_flags``, which shares a precomputed MACD/EMA(13) of
    ``weekly_ohlcv['close']`` across two ``evaluate_tide`` calls) can validate first and get
    the same fail-fast ``ValueError`` contract, instead of raising a bare ``KeyError`` from its
    own premature column access -- see the ``portfolio-exit-rules-followups`` task's
    `decisions` entry.

    Unlike the daily-side validator, a ``weekly_ohlcv`` with fewer than 2 rows is *not* treated
    as an error here: ``evaluate_tide`` itself degrades gracefully to NEUTRAL for that case
    (see its docstring) without ever touching ``'close'``, so this only guards the
    missing-column case that would otherwise raise a bare ``KeyError`` once there's enough
    history to reach the column access.

    Raises:
        ValueError: if ``weekly_ohlcv`` is missing the ``close`` column.
    """
    if "close" not in weekly_ohlcv.columns:
        raise ValueError("weekly_ohlcv is missing required column(s): ['close']")


def evaluate_tide(
    weekly_ohlcv: pd.DataFrame,
    *,
    histogram: pd.Series | None = None,
    ema_13: pd.Series | None = None,
    ema_26: pd.Series | None = None,
) -> TideResult:
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

    ``histogram``/``ema_13``/``ema_26``, if given, are used as the
    already-computed ``macd_components(weekly_ohlcv['close']).histogram`` /
    ``ema(weekly_ohlcv['close'], 13)`` / ``macd_components(...).ema_slow``
    instead of recomputing them here (each must be index-aligned with
    ``weekly_ohlcv``, i.e. the exact output of calling those functions on
    ``weekly_ohlcv['close']``). All three are independent (a caller may supply
    any subset); anything omitted is computed internally exactly as before this
    parameter existed. This lets a caller who evaluates the tide over more than
    one slice of the same underlying weekly series -- e.g.
    ``app.portfolio.exits.evaluate_exit_flags``, which calls this twice
    (``weekly_ohlcv`` and ``weekly_ohlcv[:-1]``) to detect a bullish-to-bearish
    flip -- compute the MACD/EMA series once over the full series and slice it
    per call (EMA/MACD are causal: a value at index *t* depends only on data up
    to *t*, so slicing a full-series computation gives identical values to
    recomputing over the truncated series) instead of each call independently
    re-deriving its own MACD/EMA pass -- see the
    ``portfolio-exit-rules-followups`` task's `decisions` entry.

    Raises:
        ValueError: if ``weekly_ohlcv`` has 2 or more rows but is missing the ``close``
            column -- validated via ``validate_weekly_ohlcv_columns`` so this doesn't instead
            raise a bare ``KeyError`` from the access below. A ``weekly_ohlcv`` with fewer
            than 2 rows never raises, regardless of its columns -- see the "too little
            history" behavior above.
    """
    if len(weekly_ohlcv) < 2:
        return TideResult(trend="NEUTRAL", weekly_macd_histogram_slope="flat")

    validate_weekly_ohlcv_columns(weekly_ohlcv)

    weekly_close = weekly_ohlcv["close"]
    latest_close = weekly_close.iloc[-1]

    if histogram is None or ema_26 is None:
        components = macd_components(weekly_close)
        if histogram is None:
            histogram = components.histogram
        if ema_26 is None:
            ema_26 = components.ema_slow
    slope = macd_histogram_slope(histogram, latest_close)

    if ema_13 is None:
        ema_13 = ema(weekly_close, 13)

    ema_13_latest = ema_13.iloc[-1]
    ema_26_latest = ema_26.iloc[-1]

    if slope == "rising" and ema_13_latest > ema_26_latest:
        trend = "BULLISH"
    elif slope == "falling" and ema_13_latest < ema_26_latest:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return TideResult(trend=trend, weekly_macd_histogram_slope=slope)


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

    Only ever reads the trailing ``_FORCE_INDEX_SPIKE_WINDOW`` bars of ``force_index_2ema``
    (see the slice below) -- a caller (``analyse_history()``, via ``evaluate_wave``/
    ``_wave_lookback``) may hand this a much longer series representing a growing history
    window, but ``rolling(window=_FORCE_INDEX_SPIKE_WINDOW)`` followed by ``.iloc[-1]`` only
    ever reads that trailing window's own worth of data regardless of how much of the series
    precedes it, so pre-slicing first turns this into O(1) work per call instead of
    O(len(force_index_2ema)) (docs/tasks/api-stocks-indicator-history-followups-followups.json)
    -- the computed value is unchanged either way, since a rolling standard deviation at a
    fixed position never depends on rows outside its own window.
    """
    latest = force_index_2ema.iloc[-1]
    if pd.isna(latest):
        return False

    # Signed multiplier rather than an `if negative: ... else: ...` pair of sign checks --
    # `sign * latest <= 0` reads directly as "wrong sign (or zero)" for whichever direction
    # was requested, instead of forcing a reader through `negative and latest >= 0` /
    # `not negative and latest <= 0`'s double-negative branches to see the same thing.
    sign = -1 if negative else 1
    if sign * latest <= 0:
        return False

    # Sliced to the trailing window *before* `.rolling(...).std()`, not after -- rolling over
    # the full (potentially much longer) series just to discard every value but the last is
    # O(len(force_index_2ema)) work for an O(1)-shaped question. `.iloc[-_FORCE_INDEX_SPIKE_
    # WINDOW:]` on a series shorter than the window returns the whole (too-short) series
    # unchanged, so the "not enough history yet" NaN case below is unaffected.
    trailing_window = force_index_2ema.iloc[-_FORCE_INDEX_SPIKE_WINDOW:]
    rolling_std = trailing_window.rolling(window=_FORCE_INDEX_SPIKE_WINDOW).std().iloc[-1]
    if pd.isna(rolling_std) or rolling_std == 0:
        return False

    return bool(abs(latest) > _FORCE_INDEX_SPIKE_STDEV_MULTIPLIER * rolling_std)


def evaluate_wave(
    daily_ohlcv: pd.DataFrame,
    tide: str,
    *,
    stochastic_k: pd.Series | None = None,
    force_index_2ema: pd.Series | None = None,
) -> dict:
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
    raising, for the same data-availability reason ``evaluate_impulse``'s guard exists in
    ``app/signals/impulse.py`` (a different module from this one, ``triple_screen.py``): with
    zero rows there's no bar to read ``.iloc[-1]`` from. The condition here is
    ``len(daily_ohlcv) == 0`` rather than ``evaluate_impulse``'s ``len(daily_ohlcv) < 2``,
    because unlike that function's ``_direction`` helper (which reads ``.iloc[-2]`` and so
    needs 2 rows), everything below reads only the single latest bar via ``.iloc[-1]`` --
    ``stochastic_oscillator``/``force_index`` already return NaN rather than raising when given
    just 1 row, so a 1-row ``daily_ohlcv`` reaches ``"NO_WAVE"`` through the ordinary
    NaN-degrades-to-``"NO_WAVE"`` path below instead of needing its own guard (see
    ``test_single_row_daily_ohlcv_degrades_to_no_wave_instead_of_raising``).

    ``stochastic_k``/``force_index_2ema``, if given, are used as the already-computed
    ``stochastic_oscillator(daily_ohlcv['high'], daily_ohlcv['low'], daily_ohlcv['close'])['k']``
    / ``force_index(daily_ohlcv['close'], daily_ohlcv['volume'], ema_period=2)`` instead of
    recomputing them here (each must be index-aligned with ``daily_ohlcv``, i.e. the exact
    output of calling those functions on ``daily_ohlcv`` itself -- or an equal-length prefix
    slice of a call against a longer frame whose own leading rows equal ``daily_ohlcv``, since
    both are causal/rolling-window indicators: a value at index *t* depends only on data up to
    *t*, so slicing a full-series computation gives identical values to recomputing over the
    truncated series). Both are independent (a caller may supply either, both, or neither);
    anything omitted is computed internally exactly as before this parameter existed. This lets
    a caller who evaluates the wave over many growing prefixes of the same underlying daily
    series -- ``app.signals.engine.analyse_history`` (once per bar) and its own
    ``_wave_lookback`` (up to ``_WAVE_LOOKBACK_DAYS`` more times per bar, for the "showed"
    lookback) -- compute the Stochastic/Force Index series once over the full series and slice
    it per call instead of each call independently re-deriving its own rolling-window pass --
    see the ``api-stocks-indicator-history-followups`` task's `decisions` entry.
    """
    if len(daily_ohlcv) == 0:
        return {
            "stochastic_k": float("nan"),
            "force_index_2ema": float("nan"),
            "state": "NO_WAVE",
        }

    if stochastic_k is None:
        stochastic_k = stochastic_oscillator(
            daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"]
        )["k"]
    if force_index_2ema is None:
        force_index_2ema = force_index(daily_ohlcv["close"], daily_ohlcv["volume"], ema_period=2)

    stochastic_k_latest = stochastic_k.iloc[-1]
    force_index_latest = force_index_2ema.iloc[-1]

    state = "NO_WAVE"
    if not pd.isna(stochastic_k_latest):
        if (
            tide == "BULLISH"
            and stochastic_k_latest < STOCHASTIC_OVERSOLD
            and _is_force_index_spike(force_index_2ema, negative=True)
        ):
            state = "OVERSOLD_PULLBACK"
        elif (
            tide == "BEARISH"
            and stochastic_k_latest > STOCHASTIC_OVERBOUGHT
            and _is_force_index_spike(force_index_2ema, negative=False)
        ):
            state = "OVERBOUGHT_RALLY"

    return {
        "stochastic_k": float(stochastic_k_latest),
        "force_index_2ema": float(force_index_latest),
        "state": state,
    }


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2).

    This is a daily-bar EOD approximation of Elder's classic intraday buy-stop/sell-stop
    trigger, per docs/Analyse.md §2 ("For a daily-bar app (no intraday feed required),
    approximate with...") and §10, which recommends end-of-day-only evaluation for the MVP
    given that same approximation -- see this task's `decisions` entry for confirmation this
    is still the intended approach.

    Bullish trigger (tide == "BULLISH") fires when today's close is strictly above
    yesterday's high; bearish trigger (tide == "BEARISH") fires when today's close is
    strictly below yesterday's low. Returns the exact shape docs/architecture/API.md's
    `screens.trigger` documents: ``{"fired": bool, "reference": str}``. `reference` names
    which directional rule applies given the tide ('close_above_prior_high' /
    'close_below_prior_low'), or 'not_applicable' when the tide is NEUTRAL (no directional
    rule applies) or there are fewer than two daily bars to compare (no prior bar to
    reference against at all) -- in both cases `fired` is False rather than forcing a guess.
    """
    if tide == "BULLISH":
        reference = "close_above_prior_high"
    elif tide == "BEARISH":
        reference = "close_below_prior_low"
    else:
        return {"fired": False, "reference": "not_applicable"}

    if len(daily_ohlcv) < 2:
        return {"fired": False, "reference": "not_applicable"}

    today_close = daily_ohlcv["close"].iloc[-1]
    prior_high = daily_ohlcv["high"].iloc[-2]
    prior_low = daily_ohlcv["low"].iloc[-2]

    fired = today_close > prior_high if tide == "BULLISH" else today_close < prior_low

    return {"fired": fired, "reference": reference}
