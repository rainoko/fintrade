from dataclasses import dataclass, field

import pandas as pd

from app.indicators.ema import ema
from app.indicators.elder_ray import bear_power as elder_bear_power
from app.indicators.elder_ray import bull_power as elder_bull_power
from app.indicators.macd import macd_components
from app.signals.confidence import (
    WEIGHTS,
    ConfidenceComponent,
    compute_confidence,
    confidence_band,
    score_elder_ray_confirmation,
    score_impulse_gate,
    score_oscillator_extremity,
    score_tide_alignment,
    score_volume_confirmation,
)
from app.signals.impulse import evaluate_impulse
from app.signals.triple_screen import evaluate_tide, evaluate_trigger, evaluate_wave

# How many trailing daily bars (today inclusive) evaluate_wave's qualifying oversold/
# overbought state is allowed to have appeared on before today, for the "Wave shows/showed"
# language in docs/Analyse.md §5 -- see this task's `decisions` entry for why this exists and
# why 5 was chosen.
_WAVE_LOOKBACK_DAYS = 5

# 20-day volume average window, for the "trigger bar volume ... above 20-day average" half of
# docs/Analyse.md §6's volume-confirmation component.
_VOLUME_AVERAGE_WINDOW = 20


@dataclass
class SignalResult:
    signal: str  # 'BUY' | 'SELL' | 'HOLD'
    confidence: int
    confidence_band: str
    breakdown: list[ConfidenceComponent]
    screens: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)


def _latest(series: pd.Series) -> float:
    """The last value of ``series`` as a plain float, or NaN if ``series`` is empty.

    Every per-indicator series this module reads (EMA, MACD-Histogram, Bull/Bear Power,
    volume/its rolling average) degrades to an empty or NaN-tailed Series on insufficient
    history rather than raising (see ``app.indicators.ema.ema``, ``app.indicators.macd``,
    ``app.indicators.elder_ray``) -- this centralizes "read the latest point, or NaN if
    there isn't one" so ``analyse()`` doesn't need an ``IndexError`` guard at every call site.
    """
    if len(series) == 0:
        return float("nan")
    return float(series.iloc[-1])


def _wave_showed_state(daily_ohlcv: pd.DataFrame, tide: str, target_state: str) -> bool:
    """True if ``evaluate_wave`` would have classified any of the last ``_WAVE_LOOKBACK_DAYS``
    daily bars (today inclusive) as ``target_state``, not just today's bar.

    docs/Analyse.md §5 phrases the Wave condition as "shows/showed" ("Wave shows/showed
    oversold pullback, Trigger fired") -- explicitly allowing the pullback/rally to have
    already ended by the day the Trigger actually fires, since Screen 3's trigger (today's
    close crossing back above/below the prior bar) is itself evidence the pullback/rally is
    over. ``evaluate_wave`` (screen2-wave) only ever reports the *latest* bar's state, by
    design (see that task's own `decisions` entry rejecting a persisted/partial state), so
    reproducing "showed" here means re-evaluating it over each of the last few bars using the
    full history available up to that bar -- not adding a second, competing state-persistence
    concept to evaluate_wave itself. See this task's `decisions` entry for the chosen window
    (5 trading days) and for why the tide direction is held fixed at today's value across the
    whole window rather than being recomputed per day.
    """
    n = len(daily_ohlcv)
    if n == 0:
        return False
    start = max(1, n - _WAVE_LOOKBACK_DAYS + 1)
    for end in range(start, n + 1):
        if evaluate_wave(daily_ohlcv.iloc[:end], tide)["state"] == target_state:
            return True
    return False


def _determine_signal(
    tide: str, impulse: str, wave_showed_pullback: bool, wave_showed_rally: bool, trigger_fired: bool
) -> str:
    """BUY / SELL / HOLD from the four Screen/gate inputs, per docs/Analyse.md §5's rules:

    - BUY: Tide BULLISH, Impulse != RED (the gate), Wave shows/showed an oversold pullback,
      Trigger fired (close > prior high).
    - SELL: Tide BEARISH, Impulse != GREEN (the gate), Wave shows/showed an overbought rally,
      Trigger fired (close < prior low).
    - HOLD: anything else -- Tide NEUTRAL, a directional Tide missing any one of the other
      three conditions, or an Impulse-gated combination (RED blocking a would-be BUY, GREEN
      blocking a would-be SELL) -- matching §5's "conditions partially met, conflicting, or
      Neutral tide" HOLD definition exactly, with no separate "blocked" outcome distinct from
      HOLD (§3: a RED-gated BUY setup "cap[s] confidence or downgrade[s] to Hold").
    """
    if tide == "BULLISH" and impulse != "RED" and wave_showed_pullback and trigger_fired:
        return "BUY"
    if tide == "BEARISH" and impulse != "GREEN" and wave_showed_rally and trigger_fired:
        return "SELL"
    return "HOLD"


def analyse(ticker: str, daily_ohlcv: pd.DataFrame, weekly_ohlcv: pd.DataFrame) -> SignalResult:
    """Orchestrates Screens 1-3 + Impulse gate + confidence scoring into one signal.

    See docs/architecture/Backend.md §5 and docs/Analyse.md §5. Evaluates, in the order
    docs/Analyse.md §5 lists them:

    1. Screen 1 (Tide) -- ``evaluate_tide(weekly_ohlcv)``.
    2. Impulse -- ``evaluate_impulse(daily_ohlcv)``, the gate.
    3. Screen 2 (Wave) -- ``evaluate_wave(daily_ohlcv, tide)``, today's bar, plus a lookback
       over the last few bars for the "shows/showed" case (see ``_wave_showed_state``).
    4. Screen 3 (Trigger) -- ``evaluate_trigger(daily_ohlcv, tide)``, today's bar.

    then combines them into BUY/SELL/HOLD (``_determine_signal``) and, for a fresh BUY/SELL
    only, computes the docs/Analyse.md §6 confidence score from today's snapshot of each
    component (not the historical "showed" bar, even when that's what qualified the signal --
    see this task's `decisions` entry for why). A HOLD signal has no meaningful
    ``signal_direction`` for the confidence components (each of which requires 'BUY' or
    'SELL' and raises otherwise -- see ``app.signals.confidence``), so HOLD always returns
    ``confidence=0``, ``confidence_band="Low"``, and an empty ``breakdown`` rather than
    fabricating a direction to score against.

    The returned ``SignalResult`` also carries ``screens`` (the ``docs/architecture/API.md``
    ``screens.{tide,impulse,wave,trigger}`` shape) and ``indicators`` (its
    ``indicators.{ema_13,ema_26,macd_histogram,bull_power,bear_power}`` shape) -- both always
    populated regardless of ``signal``, since they're informational context for the API
    response, not signal-gated -- so a caller (the not-yet-implemented api-stocks-analysis
    task) can map this one result directly onto ``AnalysisResponse`` without recomputing
    anything itself. See this task's `decisions` entry for why this is broader than the
    literal "(signal, confidence, breakdown)" tuple docs/architecture/Backend.md §5 and this
    module's own pre-existing docstring describe.

    An empty or very short ``daily_ohlcv``/``weekly_ohlcv`` degrades gracefully to HOLD
    (tide NEUTRAL, impulse BLUE, wave NO_WAVE/NaN, trigger not_applicable -- each already
    handled by the respective Screen/gate function) with ``indicators`` values of NaN, rather
    than raising; this module adds no additional minimum-history check of its own beyond what
    Screens 1-3/Impulse already enforce individually.
    """
    tide_result = evaluate_tide(weekly_ohlcv)
    tide = tide_result.trend
    impulse = evaluate_impulse(daily_ohlcv)
    wave = evaluate_wave(daily_ohlcv, tide)
    trigger = evaluate_trigger(daily_ohlcv, tide)

    wave_showed_pullback = _wave_showed_state(daily_ohlcv, tide, "OVERSOLD_PULLBACK")
    wave_showed_rally = _wave_showed_state(daily_ohlcv, tide, "OVERBOUGHT_RALLY")
    signal = _determine_signal(tide, impulse, wave_showed_pullback, wave_showed_rally, trigger["fired"])

    daily_close = daily_ohlcv["close"]
    ema_13_series = ema(daily_close, 13)
    ema_26_series = ema(daily_close, 26)
    histogram_series = macd_components(daily_close).histogram
    bull_power_series = elder_bull_power(daily_ohlcv["high"], ema_13_series)
    bear_power_series = elder_bear_power(daily_ohlcv["low"], ema_13_series)

    indicators = {
        "ema_13": _latest(ema_13_series),
        "ema_26": _latest(ema_26_series),
        "macd_histogram": _latest(histogram_series),
        "bull_power": _latest(bull_power_series),
        "bear_power": _latest(bear_power_series),
    }
    screens = {
        "tide": {
            "trend": tide_result.trend,
            "weekly_macd_histogram_slope": tide_result.weekly_macd_histogram_slope,
        },
        "impulse": impulse,
        "wave": wave,
        "trigger": trigger,
    }

    if signal == "HOLD":
        breakdown: list[ConfidenceComponent] = []
        confidence = 0
    else:
        volume = daily_ohlcv["volume"]
        latest_volume = _latest(volume)
        average_volume = _latest(volume.rolling(window=_VOLUME_AVERAGE_WINDOW).mean())
        breakdown = [
            ConfidenceComponent(
                "tide_alignment", WEIGHTS["tide_alignment"], score_tide_alignment(tide, signal)
            ),
            ConfidenceComponent(
                "impulse_gate", WEIGHTS["impulse_gate"], score_impulse_gate(impulse, signal)
            ),
            ConfidenceComponent(
                "oscillator_extremity",
                WEIGHTS["oscillator_extremity"],
                score_oscillator_extremity(wave, signal),
            ),
            ConfidenceComponent(
                "elder_ray_confirmation",
                WEIGHTS["elder_ray_confirmation"],
                score_elder_ray_confirmation(bull_power_series, bear_power_series, signal),
            ),
            ConfidenceComponent(
                "volume_confirmation",
                WEIGHTS["volume_confirmation"],
                score_volume_confirmation(wave["state"], latest_volume, average_volume),
            ),
        ]
        confidence = compute_confidence(breakdown)

    return SignalResult(
        signal=signal,
        confidence=confidence,
        confidence_band=confidence_band(confidence),
        breakdown=breakdown,
        screens=screens,
        indicators=indicators,
    )
