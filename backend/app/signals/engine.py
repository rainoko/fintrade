from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.indicators.elder_ray import bear_power as elder_bear_power
from app.indicators.elder_ray import bull_power as elder_bull_power
from app.indicators.ema import ema
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
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: int
    confidence_band: Literal["Low", "Medium", "High"]
    breakdown: list[ConfidenceComponent]
    screens: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)


def drop_malformed_daily_bars(
    daily_ohlcv: pd.DataFrame, *, require_full_ohlc_on_latest_bar: bool = True
) -> pd.DataFrame:
    """Drop any daily bar whose open/high/low/close aren't all real numbers.

    A real, observed yfinance condition: the most recent daily bar can come back with NaN
    open/high/low/close and only ``volume`` populated, before that session's data has fully
    settled on the provider's end (see this task's `decisions` entry on
    docs/tasks/api-stocks-analysis-nullable-indicators.json, which discovered this via a
    frontend crash on the resulting null ``Indicators``/``WaveScreen`` fields). Treating such
    a bar as "not yet arrived" -- excluded outright, not merely NaN-tolerated -- rather than
    letting it flow into every daily-resolution computation matters for more than just
    ``indicators``/``screens.wave``'s leaf fields: ``evaluate_trigger``'s
    ``today_close > prior_high`` silently evaluates to ``False`` for a NaN ``today_close``
    (a NaN comparison, not an error), so a malformed latest bar could silently suppress a
    real BUY/SELL signal without ever surfacing as a visible null anywhere in the response --
    a worse, harder-to-detect bug than a null indicator would be. Excluding the bar up front
    keeps both the signal computation itself and the ``Indicators``/``WaveScreen`` schema's
    non-Optional ``float`` contract honest, and mirrors the existing
    ``app.data.stooq_provider.StooqProvider._resample_weekly``
    ``dropna(subset=["open", "high", "low", "close"])`` precedent for the same kind of
    malformed-bar hygiene.

    Applied across the whole frame, not just the trailing bar -- a malformed bar anywhere in
    history is equally unfit to feed into the rolling/EMA computations that read across the
    full series, not just the ones that read a single latest bar. An empty (0-row) or
    already-clean frame passes through unchanged (``dropna`` is a no-op in both cases).

    Only checks whichever of ``open``/``high``/``low``/``close`` are actually present in
    ``daily_ohlcv`` -- a frame missing one of those columns entirely (a distinct, pre-existing
    failure mode from the NaN-*value* one this function targets) is left for the caller's own
    column-presence check (e.g. ``app.portfolio.risk.validate_daily_ohlcv_columns``) to raise
    its documented ``ValueError`` for, rather than this function raising a bare ``KeyError``
    from ``dropna(subset=...)`` naming a column that was never there -- see the
    api-stocks-analysis-nullable-indicators-followups task's `decisions` entry (found via
    GET /api/portfolio/risk's malformed-daily-frame test fixtures, which simulate a
    missing-column frame to exercise exactly that downstream check).

    ``require_full_ohlc_on_latest_bar`` (default ``True``, this function's original behavior,
    still what ``app.signals.engine.analyse``/``app.api.routers.stocks.get_analysis`` use):
    when ``False``, the *latest* bar is dropped only if its own ``close`` is NaN (or missing --
    left for the caller's own column check, same as above); every earlier bar still needs full
    OHLC validity exactly as when this parameter is ``True``. Pass ``False`` only from a caller
    whose downstream computation never reads the latest bar's own open/high/low at all --
    currently just ``app.api.routers.portfolio.get_risk``'s exit-flag pipeline (``app.portfolio
    .exits.evaluate_exit_flags`` and everything it calls -- ``protective_stop``, ``autoenvelope``,
    ``evaluate_impulse`` -- read the latest bar's ``close`` only; the *older* bars' ``low`` still
    feeds ``protective_stop``'s swing-low window, which is why they still need full validity).
    Using the default (``True``) there would silently desync ``position.current_price``
    (``app.portfolio.pricing._latest_close``, which only ever checks the latest bar's ``close``
    for NaN) from ``daily_ohlcv``'s own last row once filtered -- a real stop-hit could then be
    missed by testing a stale prior close instead of today's -- see the
    api-stocks-analysis-nullable-indicators-followups task's `decisions` entry for the full
    reasoning and the regression this reconciles.
    """
    required_columns = ["open", "high", "low", "close"]
    present_columns = [column for column in required_columns if column in daily_ohlcv.columns]
    if require_full_ohlc_on_latest_bar or daily_ohlcv.empty:
        return daily_ohlcv.dropna(subset=present_columns)

    history, latest = daily_ohlcv.iloc[:-1], daily_ohlcv.iloc[[-1]]
    history = history.dropna(subset=present_columns)
    if "close" in latest.columns and pd.isna(latest.iloc[0]["close"]):
        latest = latest.iloc[0:0]
    return pd.concat([history, latest])


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


def _wave_lookback(daily_ohlcv: pd.DataFrame, tide: str) -> tuple[dict, bool, bool]:
    """Today's Wave (Screen 2) result, plus whether the last ``_WAVE_LOOKBACK_DAYS`` daily
    bars (today inclusive) "show/showed" the oversold-pullback or overbought-rally state, in
    a single pass over ``evaluate_wave``.

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

    Returns ``(wave, wave_showed_pullback, wave_showed_rally)``, where ``wave`` is today's
    ``evaluate_wave(daily_ohlcv, tide)`` result (the "shows" case, read off this same pass
    rather than calling ``evaluate_wave`` on the full history a second time) and the two
    booleans are whether ``OVERSOLD_PULLBACK``/``OVERBOUGHT_RALLY`` respectively appeared
    anywhere in the lookback window.

    ``evaluate_wave`` can only ever produce ``OVERSOLD_PULLBACK`` when ``tide == "BULLISH"``
    and only ever produce ``OVERBOUGHT_RALLY`` when ``tide == "BEARISH"`` -- never both for a
    given (fixed, per this function's own contract) tide. So only one of the two "showed"
    booleans is ever reachable per call; the other is set to False directly without spending
    any further ``evaluate_wave`` calls scanning a window it could never match -- see this
    task's `decisions` entry (this used to cost up to 11 ``evaluate_wave`` calls per
    ``analyse()`` invocation: one direct call for today's bar, plus two independent
    ``_WAVE_LOOKBACK_DAYS``-bar lookback loops, one of which was always fully wasted).
    Within the achievable direction, the scan checks today's bar first (already computed
    above) and walks backwards, stopping as soon as a match is found rather than always
    re-deriving the full window.
    """
    n = len(daily_ohlcv)
    wave = evaluate_wave(daily_ohlcv, tide)
    if tide == "BULLISH":
        target_state = "OVERSOLD_PULLBACK"
    elif tide == "BEARISH":
        target_state = "OVERBOUGHT_RALLY"
    else:
        target_state = None

    showed_target = target_state is not None and wave["state"] == target_state
    if target_state is not None and not showed_target and n > 0:
        start = max(1, n - _WAVE_LOOKBACK_DAYS + 1)
        for end in range(n - 1, start - 1, -1):
            if evaluate_wave(daily_ohlcv.iloc[:end], tide)["state"] == target_state:
                showed_target = True
                break

    wave_showed_pullback = showed_target if target_state == "OVERSOLD_PULLBACK" else False
    wave_showed_rally = showed_target if target_state == "OVERBOUGHT_RALLY" else False
    return wave, wave_showed_pullback, wave_showed_rally


def _determine_signal(
    tide: str, impulse: str, wave_showed_pullback: bool, wave_showed_rally: bool, trigger_fired: bool
) -> Literal["BUY", "SELL", "HOLD"]:
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
    2. Impulse -- ``evaluate_impulse(daily_ohlcv, ema_13=..., histogram=...)``, the gate,
       sharing its EMA(13)/MACD-Histogram inputs with the ``indicators`` dict below instead
       of each recomputing its own copy (see this task's `decisions` entry).
    3. Screen 2 (Wave) -- ``evaluate_wave(daily_ohlcv, tide)``, today's bar, plus a lookback
       over the last few bars for the "shows/showed" case (see ``_wave_lookback``, which
       computes both in a single pass).
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

    ``daily_ohlcv`` has any malformed bar (NaN open/high/low/close, a real observed
    unsettled-latest-bar condition) dropped via ``drop_malformed_daily_bars`` before anything
    else reads it, so a malformed bar can neither leak NaN into ``indicators``/``screens.wave``
    nor silently corrupt Screen 2/3's or the Impulse gate's own comparisons -- see this task's
    `decisions` entry and ``drop_malformed_daily_bars``'s own docstring for why this lives here
    rather than only being tolerated downstream.
    """
    daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)

    tide_result = evaluate_tide(weekly_ohlcv)
    tide = tide_result.trend

    daily_close = daily_ohlcv["close"]
    ema_13_series = ema(daily_close, 13)
    ema_26_series = ema(daily_close, 26)
    histogram_series = macd_components(daily_close).histogram

    impulse = evaluate_impulse(daily_ohlcv, ema_13=ema_13_series, histogram=histogram_series)
    wave, wave_showed_pullback, wave_showed_rally = _wave_lookback(daily_ohlcv, tide)
    trigger = evaluate_trigger(daily_ohlcv, tide)

    signal = _determine_signal(tide, impulse, wave_showed_pullback, wave_showed_rally, trigger["fired"])

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


def _weekly_through_bar_date(weekly_ohlcv: pd.DataFrame, bar_date: pd.Timestamp) -> pd.DataFrame:
    """Truncates ``weekly_ohlcv`` to only the weekly bars whose own label falls within or
    before the calendar week (Saturday-through-Friday) that *contains* ``bar_date`` -- not to
    weekly bars whose label is ``<= bar_date`` directly.

    ``app.data.stooq_provider.StooqProvider._resample_weekly`` builds ``weekly_ohlcv`` via
    ``daily.resample("W-FRI")``, which bins each Saturday-through-Friday span and labels it
    with that span's Friday -- so a bar that fell on, say, a Wednesday shares its bin (and its
    weekly bar's label) with every other day Monday-through-Friday of that same week, and that
    label is often a date *after* the Wednesday bar itself, including possibly today's
    still-forming week. A naive ``weekly_ohlcv.index <= bar_date`` filter would incorrectly
    drop that in-progress week's bar for every bar_date that isn't itself a Friday-or-later --
    wrong for the "no look-ahead" bars this function serves, and, at the series' own most
    recent bar, exactly the failure this task's prior (rejected) attempt at per-day truncation
    ran into: it would drop the current week's bar even there, disagreeing with
    ``GET /api/stocks/{ticker}/analysis``'s own (fully untruncated) weekly snapshot.

    Computing the Friday of ``bar_date``'s own week instead resolves both: every bar within
    the same calendar week maps to the same truncation cutoff (that week's Friday), and for
    the most recent daily bar specifically, that cutoff is -- by construction, since
    ``weekly_ohlcv`` was built from a resample keyed the same way -- exactly the label of
    ``weekly_ohlcv``'s own last row, so the filter keeps the full series unchanged and the
    "last point matches ``/analysis``" invariant holds without special-casing it.
    """
    # `pd.DateOffset`, not `pd.Timedelta` -- see `app.api.routers.stocks._trim_to_range`'s
    # comment on the same NumPy/pandas DeprecationWarning `pd.Timedelta(days=...)` alone trips
    # on this pairing.
    week_friday = bar_date + pd.DateOffset(days=(4 - bar_date.weekday()) % 7)
    return weekly_ohlcv[weekly_ohlcv.index <= week_friday]


def analyse_history(
    ticker: str,
    daily_ohlcv: pd.DataFrame,
    weekly_ohlcv: pd.DataFrame,
    *,
    from_index: int = 0,
) -> list[tuple[pd.Timestamp, SignalResult]]:
    """Re-runs ``analyse()`` once per daily bar from ``from_index`` (inclusive) through the
    last bar, truncating ``daily_ohlcv`` to only the bars up to and including that day AND
    truncating ``weekly_ohlcv`` to only the weekly bars as-of that same day (see
    ``_weekly_through_bar_date``) each time -- so every historical point reflects what
    ``analyse()`` would have produced "as of" that day, including Screen 1 (Tide), not a
    replay of today's fixed Tide backwards. This is what makes the resulting per-bar
    ``signal``/``indicators`` meaningful for a chart overlay
    (``app.api.routers.stocks.get_indicator_history``, docs/Analyse.md §4-5) rather than a
    single value repeated across every date -- see this task's `decisions` entry
    (docs/tasks/api-stocks-indicator-history.json) for why this loop lives here (reusing
    ``analyse()`` unchanged) instead of duplicating any indicator/Screen math, and for why an
    earlier version of this function held ``weekly_ohlcv`` fixed (look-ahead bias on Screen 1,
    fixed by truncating per calendar week instead of per bar_date -- see
    ``_weekly_through_bar_date``'s own docstring for why that resolves the tension a naive
    ``<= bar_date`` filter ran into).

    ``daily_ohlcv``/``weekly_ohlcv`` are expected already cleaned by the caller (e.g. via
    ``drop_malformed_daily_bars``), matching every other function in this module --
    ``analyse()`` re-applies ``drop_malformed_daily_bars`` to its own truncated slice
    regardless (idempotent, negligible cost), so a malformed bar earlier in ``daily_ohlcv``
    can't leak into any truncated window either.

    ``from_index`` lets the caller skip recomputing bars it doesn't intend to return (e.g. a
    ``range``-trimmed output window) while ``daily_ohlcv`` itself still carries the full
    available history every emitted point needs for correct indicator warm-up -- passing an
    already-trimmed ``daily_ohlcv`` instead would degrade (NaN-tail) the indicators for bars
    near the start of the window. Negative values behave like ``0`` (the full series).

    Returns a list of ``(bar_date, SignalResult)`` pairs, oldest first, one per daily bar from
    ``from_index`` through the last available bar (empty if ``daily_ohlcv`` has no bars in
    that range).
    """
    n = len(daily_ohlcv)
    start = max(from_index, 0)
    return [
        (
            daily_ohlcv.index[i],
            analyse(
                ticker,
                daily_ohlcv.iloc[: i + 1],
                _weekly_through_bar_date(weekly_ohlcv, daily_ohlcv.index[i]),
            ),
        )
        for i in range(start, n)
    ]
