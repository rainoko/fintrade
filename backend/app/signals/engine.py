from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.indicators.autoenvelope import autoenvelope
from app.indicators.elder_ray import bear_power as elder_bear_power
from app.indicators.elder_ray import bull_power as elder_bull_power
from app.indicators.ema import ema
from app.indicators.force_index import force_index
from app.indicators.macd import macd_components
from app.indicators.stochastic import stochastic_oscillator
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


def _wave_lookback(
    daily_ohlcv: pd.DataFrame,
    tide: str,
    *,
    stochastic_k: pd.Series | None = None,
    force_index_2ema: pd.Series | None = None,
) -> tuple[dict, bool, bool]:
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

    ``stochastic_k``/``force_index_2ema``, if given, are passed straight through to every
    ``evaluate_wave`` call this function makes (sliced to match each call's own truncated
    ``daily_ohlcv.iloc[:end]``, per ``evaluate_wave``'s own index-alignment contract) instead
    of each of the up-to-``_WAVE_LOOKBACK_DAYS + 1`` calls independently recomputing the
    Stochastic/Force Index from scratch over its own (growing, in the caller's case) prefix of
    the daily series -- see ``evaluate_wave``'s own docstring and this task's `decisions` entry.
    """
    n = len(daily_ohlcv)
    wave = evaluate_wave(
        daily_ohlcv, tide, stochastic_k=stochastic_k, force_index_2ema=force_index_2ema
    )
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
            lookback_stochastic_k = stochastic_k.iloc[:end] if stochastic_k is not None else None
            lookback_force_index_2ema = (
                force_index_2ema.iloc[:end] if force_index_2ema is not None else None
            )
            lookback_wave = evaluate_wave(
                daily_ohlcv.iloc[:end],
                tide,
                stochastic_k=lookback_stochastic_k,
                force_index_2ema=lookback_force_index_2ema,
            )
            if lookback_wave["state"] == target_state:
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


def analyse(
    ticker: str,
    daily_ohlcv: pd.DataFrame,
    weekly_ohlcv: pd.DataFrame,
    *,
    ema_13: pd.Series | None = None,
    ema_26: pd.Series | None = None,
    histogram: pd.Series | None = None,
    stochastic_k: pd.Series | None = None,
    force_index_2ema: pd.Series | None = None,
    weekly_ema_13: pd.Series | None = None,
    weekly_ema_26: pd.Series | None = None,
    weekly_histogram: pd.Series | None = None,
    channel_upper: pd.Series | None = None,
    channel_lower: pd.Series | None = None,
    _daily_ohlcv_already_clean: bool = False,
) -> SignalResult:
    """Orchestrates Screens 1-3 + Impulse gate + confidence scoring into one signal.

    See docs/architecture/Backend.md §5 and docs/Analyse.md §5. Evaluates, in the order
    docs/Analyse.md §5 lists them:

    1. Screen 1 (Tide) -- ``evaluate_tide(weekly_ohlcv)``.
    2. Impulse -- ``evaluate_impulse(daily_ohlcv, ema_13=..., histogram=...)``, the gate,
       sharing its EMA(13)/MACD-Histogram inputs with the ``indicators`` dict below instead
       of each recomputing its own copy (see this task's `decisions` entry).
    3. Screen 2 (Wave) -- ``evaluate_wave(daily_ohlcv, tide)``, today's bar, plus a lookback
       over the last few bars for the "shows/showed" case (see ``_wave_lookback``, which
       computes both in a single pass). ``screens["wave"]`` exposes the lookback booleans
       themselves as ``showed_pullback_in_lookback``/``showed_rally_in_lookback`` (null when
       ``tide == "NEUTRAL"``, real booleans otherwise) alongside today's own ``state`` -- see
       the ``screens`` dict construction below and docs/tasks/api-stocks-analysis-wave-lookback
       .json's `decisions` entry.
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
    ``indicators.{ema_13,ema_26,macd_histogram,bull_power,bear_power,channel_upper,
    channel_lower}`` shape) -- both always
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

    ``ema_13``/``ema_26``/``histogram``/``stochastic_k``/``force_index_2ema``, if given, are
    used as the already-computed ``ema(daily_ohlcv['close'], 13)`` /
    ``ema(daily_ohlcv['close'], 26)`` / ``macd_components(daily_ohlcv['close']).histogram`` /
    ``stochastic_oscillator(daily_ohlcv['high'], daily_ohlcv['low'], daily_ohlcv['close'])['k']``
    / ``force_index(daily_ohlcv['close'], daily_ohlcv['volume'], ema_period=2)`` instead of
    recomputing them here (each must be index-aligned with ``daily_ohlcv`` post-
    ``drop_malformed_daily_bars``, exactly like ``evaluate_impulse``'s/``evaluate_tide``'s own
    equivalent parameters). All five are independent (a caller may supply any subset); anything
    omitted is computed internally exactly as before these parameters existed. This lets a
    caller who evaluates many growing prefixes of the same underlying daily series --
    ``analyse_history``, once per bar in the requested range -- compute each of these causal/
    rolling-window indicators once over the full series and slice them per call instead of every
    one of up to thousands of calls independently re-deriving its own EMA/MACD/Stochastic/Force
    Index pass from scratch (the O(range_size x history_length) cost this task's `decisions`
    entry addresses).

    ``weekly_ema_13``/``weekly_ema_26``/``weekly_histogram`` are the equivalent passthrough for
    Screen 1 -- forwarded straight to ``evaluate_tide``'s own like-named parameters (see its
    docstring), letting ``analyse_history`` share one weekly EMA/MACD pass across every bar's
    Tide evaluation the same way it does for the five daily-side parameters above, instead of
    every bar's ``evaluate_tide`` call re-deriving the weekly EMA(13)/EMA(26)/MACD-Histogram
    from scratch over its own truncated ``weekly_ohlcv`` window.

    ``channel_upper``/``channel_lower``, if given, are the already-computed
    ``autoenvelope(daily_ohlcv['close'], mid=ema_13)['upper']``/``['lower']`` (the Autoenvelope/
    channel bands, docs/Analyse.md §4: "EMA 13 ± avg % deviation") instead of this function
    computing them itself -- same passthrough contract as ``ema_13``/etc above (index-aligned
    with ``daily_ohlcv`` post-``drop_malformed_daily_bars``), letting ``analyse_history`` share
    one ``autoenvelope`` pass (itself O(n) via a rolling-window average, not O(1)) across every
    bar instead of each of up to thousands of calls independently re-deriving it. When omitted,
    this function computes them itself the same way ``app.portfolio.exits.evaluate_exit_flags``
    already does internally for the "price reaches the upper Autoenvelope band with Impulse
    turning Red" exit rule (docs/Analyse.md §7) -- sharing that same ``ema_13`` as the band's
    ``mid`` rather than letting ``autoenvelope`` recompute its own EMA(13) pass, exactly
    mirroring how ``evaluate_impulse``/the Elder-Ray calls above already share it. See this
    task's `decisions` entry (docs/tasks/backend-channel-envelope-exposure.json) for why
    EMA(13) (this app's existing ``autoenvelope`` default, matching Analyse.md's own "EMA 13"
    spec for this indicator) is used here rather than the book's own slower-EMA channel
    variant.

    ``_daily_ohlcv_already_clean`` is a private, ``analyse_history``-only optimization escape
    hatch -- not part of this function's public contract -- that skips the
    ``drop_malformed_daily_bars`` call above entirely when the caller can *prove* (not just
    promise) ``daily_ohlcv`` is already clean, because it's itself a positional prefix slice of
    a frame ``analyse_history`` already cleaned in full before ever truncating it. Every other
    caller (including every existing test) must leave this at its default ``False`` -- the
    ordinary path still re-derives cleanliness itself rather than trusting an undocumented
    caller promise. See ``analyse_history``'s own docstring for why this specific redundant
    O(i)-per-call ``dropna`` scan (repeated ``range_size`` times over an increasingly large
    slice) was worth eliminating on top of the five/eight precomputed-series parameters above.
    """
    if not _daily_ohlcv_already_clean:
        daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)

    tide_result = evaluate_tide(
        weekly_ohlcv,
        histogram=weekly_histogram,
        ema_13=weekly_ema_13,
        ema_26=weekly_ema_26,
    )
    tide = tide_result.trend

    daily_close = daily_ohlcv["close"]
    if ema_13 is None:
        ema_13 = ema(daily_close, 13)
    if ema_26 is None:
        ema_26 = ema(daily_close, 26)
    if histogram is None:
        histogram = macd_components(daily_close).histogram

    impulse = evaluate_impulse(daily_ohlcv, ema_13=ema_13, histogram=histogram)
    wave, wave_showed_pullback, wave_showed_rally = _wave_lookback(
        daily_ohlcv, tide, stochastic_k=stochastic_k, force_index_2ema=force_index_2ema
    )
    trigger = evaluate_trigger(daily_ohlcv, tide)

    signal = _determine_signal(tide, impulse, wave_showed_pullback, wave_showed_rally, trigger["fired"])

    bull_power_series = elder_bull_power(daily_ohlcv["high"], ema_13)
    bear_power_series = elder_bear_power(daily_ohlcv["low"], ema_13)

    if channel_upper is None or channel_lower is None:
        channel_bands = autoenvelope(daily_close, mid=ema_13)
        if channel_upper is None:
            channel_upper = channel_bands["upper"]
        if channel_lower is None:
            channel_lower = channel_bands["lower"]

    indicators = {
        "ema_13": _latest(ema_13),
        "ema_26": _latest(ema_26),
        "macd_histogram": _latest(histogram),
        "bull_power": _latest(bull_power_series),
        "bear_power": _latest(bear_power_series),
        "channel_upper": _latest(channel_upper),
        "channel_lower": _latest(channel_lower),
    }
    screens = {
        "tide": {
            "trend": tide_result.trend,
            "weekly_macd_histogram_slope": tide_result.weekly_macd_histogram_slope,
        },
        "impulse": impulse,
        "wave": {
            **wave,
            # `_wave_lookback`'s own booleans, plumbed straight through rather than
            # recomputed (it already computes both internally to feed `_determine_signal`
            # above) -- see docs/tasks/api-stocks-analysis-wave-lookback.json's `decisions`
            # entry for why these are exposed at all (so a client explaining a signal, e.g.
            # frontend-signal-why-explanation's SignalExplanation, can distinguish "the Wave
            # condition was met on an earlier day within the lookback window" from "it was
            # never met" -- both otherwise look identical via `state` alone) and for the
            # null-only-when-Neutral-tide shape chosen here: when `tide == "NEUTRAL"`,
            # `_wave_lookback` always returns `(False, False)` for both booleans since
            # neither is ever evaluated (Wave is read against a tide direction that doesn't
            # exist), so `False` there would misleadingly read as "checked, and it didn't
            # happen" rather than "not applicable, tide is Neutral". For a directional tide,
            # both fields are real (non-null) booleans -- including the direction that's
            # structurally always `False` for that tide (e.g. `showed_rally_in_lookback`
            # when tide is BULLISH) -- since that `False` is itself meaningful (matches
            # `_wave_lookback`'s own always-False-for-the-unreachable-direction contract),
            # not just a placeholder.
            "showed_pullback_in_lookback": None if tide == "NEUTRAL" else wave_showed_pullback,
            "showed_rally_in_lookback": None if tide == "NEUTRAL" else wave_showed_rally,
        },
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
    ``drop_malformed_daily_bars``), matching every other function in this module -- this
    function re-applies ``drop_malformed_daily_bars`` to ``daily_ohlcv`` itself up front (once,
    not per bar) regardless, both so a malformed bar earlier in ``daily_ohlcv`` can't leak into
    any truncated window (``analyse()`` would otherwise re-derive this per call on its own
    truncated slice, which is what made this idempotent either way) and, since this function
    now precomputes several daily indicator series once over the full ``daily_ohlcv`` (see
    below), so those precomputed series and every per-bar truncated slice ``analyse()`` itself
    still cleans are guaranteed to agree on which rows exist -- a caller passing already-dirty
    data straight through would otherwise risk an index-mismatch ``ValueError`` from
    ``app.indicators.elder_ray`` instead of a silently-wrong result.

    This top-level clean is a genuine, currently-dormant behavior change from this function's
    pre-precomputation implementation for a caller whose ``daily_ohlcv`` has a malformed bar
    *mid*-history (not just the trailing bar): that date's entry is now omitted from the
    returned list entirely, rather than -- the prior behavior -- still appearing in the
    output with a ``SignalResult`` duplicating the preceding clean bar's (since the malformed
    row fell out of that bar's own truncated slice inside ``analyse()``'s own, still-present,
    per-slice clean either way, leaving that slice identical to the prior bar's). See
    ``TestAnalyseHistory.test_malformed_bar_mid_history_is_dropped_from_history_entirely`` for
    a reproduction of the current (post-precomputation) behavior. The only real caller
    (``app.api.routers.stocks.get_indicator_history``) always pre-cleans ``daily_ohlcv`` before
    calling this function, so neither behavior is actually reachable in production today, and
    the new one arguably fits ``drop_malformed_daily_bars``'s own contract better (no chart
    point for a day whose data never really arrived, rather than a phantom duplicate point) --
    but it's a real, observable difference for any future caller that doesn't pre-clean, worth
    stating explicitly rather than leaving implicit in the precomputation change alone.

    ``from_index`` lets the caller skip recomputing bars it doesn't intend to return (e.g. a
    ``range``-trimmed output window) while ``daily_ohlcv`` itself still carries the full
    available history every emitted point needs for correct indicator warm-up -- passing an
    already-trimmed ``daily_ohlcv`` instead would degrade (NaN-tail) the indicators for bars
    near the start of the window. Negative values behave like ``0`` (the full series).

    Performance: naively calling ``analyse()`` once per bar on an ``i``-bar-growing slice of
    ``daily_ohlcv`` would make every one of its EMA(13)/EMA(26)/MACD-Histogram/Stochastic/Force
    Index/Autoenvelope computations -- each themselves O(i) -- recompute from scratch each time,
    an O(range_size x history_length) total cost that's a real multi-second-plus latency risk for
    ``range=max`` on a ticker with years of daily history (see this task's `decisions` entry,
    docs/tasks/api-stocks-indicator-history-followups.json). All six of those daily indicator
    series -- plus, on the weekly side, Screen 1 (Tide)'s own EMA(13)/EMA(26)/MACD-Histogram --
    are causal/rolling-window (a value at index *t* depends only on data up to *t*), so this
    function instead computes each of them exactly once over the full (cleaned) ``daily_ohlcv``/
    ``weekly_ohlcv`` and passes ``analyse()`` a same-truncated *slice* of each precomputed series
    per bar (via ``analyse()``'s own ``ema_13``/``ema_26``/``histogram``/``stochastic_k``/
    ``force_index_2ema``/``channel_upper``/``channel_lower``/``weekly_ema_13``/
    ``weekly_ema_26``/``weekly_histogram`` parameters -- see its docstring) -- a cheap
    positional ``.iloc[:k]`` slice, not a recomputation -- instead of letting ``analyse()``
    (and, transitively, ``_wave_lookback``/``evaluate_wave``/``evaluate_tide``) rederive them
    from each bar's own truncated ``daily_ohlcv``/``weekly_ohlcv`` window. This turns the
    dominant cost of the O(range_size x history_length) total into O(history_length), not the
    *entire* cost -- ``elder_bull_power``/``elder_bear_power`` (a vectorized High/Low - EMA(13)
    subtraction) are *not* among the series precomputed here, since ``analyse()`` computes them
    itself from its own truncated ``daily_ohlcv``/``ema_13`` slice every call; along with the
    already-acknowledged per-bar volume-rolling-average (the confidence-scoring branch) and
    ``_weekly_through_bar_date`` boolean-mask costs, this leaves a residual O(i)-per-bar term, so
    the function's true worst-case asymptotic complexity remains O(range_size x history_length)
    -- just with a much smaller constant, since the six/nine precomputed series above were the
    dominant terms.
    Confirmed empirically this residual cost doesn't matter in practice for realistic history
    lengths (a synthetic worst-case benchmark engineered to hit the Wave screen's oversold/
    Force-Index-spike path as often as possible still showed clean linear, not quadratic,
    scaling up to several thousand bars -- see this task's `decisions` entry,
    docs/tasks/api-stocks-indicator-history-followups-followups.json), which is why
    ``elder_bull_power``/``elder_bear_power`` were left as-is rather than extended into the
    same precompute-and-slice pattern. The weekly series is precomputed only
    when it actually has enough history/columns for ``evaluate_tide`` to use them (2+ rows and
    a ``close`` column) -- otherwise every call hits ``evaluate_tide``'s own (cheap, guard-clause)
    NEUTRAL/missing-column path regardless, so there's nothing worth precomputing. This function
    also passes ``analyse()``'s private ``_daily_ohlcv_already_clean=True`` (see its docstring),
    since ``daily_ohlcv`` was already fully cleaned once above -- avoiding a further redundant
    O(i)-per-bar ``drop_malformed_daily_bars``/``dropna`` rescan of each bar's own (already-clean)
    truncated slice, which profiling showed was otherwise the single largest remaining cost even
    after the precomputation above.

    Returns a list of ``(bar_date, SignalResult)`` pairs, oldest first, one per daily bar from
    ``from_index`` through the last available bar (empty if ``daily_ohlcv`` has no bars in
    that range).
    """
    daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)

    n = len(daily_ohlcv)
    start = max(from_index, 0)
    if start >= n:
        return []

    daily_close = daily_ohlcv["close"]
    ema_13_full = ema(daily_close, 13)
    ema_26_full = ema(daily_close, 26)
    histogram_full = macd_components(daily_close).histogram
    stochastic_k_full = stochastic_oscillator(
        daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"]
    )["k"]
    force_index_2ema_full = force_index(daily_ohlcv["close"], daily_ohlcv["volume"], ema_period=2)
    channel_bands_full = autoenvelope(daily_close, mid=ema_13_full)
    channel_upper_full = channel_bands_full["upper"]
    channel_lower_full = channel_bands_full["lower"]

    weekly_ema_13_full = weekly_ema_26_full = weekly_histogram_full = None
    if len(weekly_ohlcv) >= 2 and "close" in weekly_ohlcv.columns:
        weekly_close = weekly_ohlcv["close"]
        weekly_ema_13_full = ema(weekly_close, 13)
        weekly_macd_full = macd_components(weekly_close)
        weekly_ema_26_full = weekly_macd_full.ema_slow
        weekly_histogram_full = weekly_macd_full.histogram

    results = []
    for i in range(start, n):
        bar_date = daily_ohlcv.index[i]
        weekly_window = _weekly_through_bar_date(weekly_ohlcv, bar_date)
        weekly_kwargs: dict[str, pd.Series] = {}
        if (
            weekly_ema_13_full is not None
            and weekly_ema_26_full is not None
            and weekly_histogram_full is not None
        ):
            # `weekly_window` is always the leading (earliest) rows of ``weekly_ohlcv`` --
            # ``_weekly_through_bar_date``'s boolean ``index <= week_friday`` mask over a
            # sorted-ascending index can only ever keep a prefix -- so a cheap positional
            # ``.iloc[:k]`` slice of each precomputed full series lands on the exact same rows
            # a label-based ``.loc[weekly_window.index]`` lookup would, at a fraction of the
            # per-call cost (no index-equality/type-checking machinery).
            weekly_window_length = len(weekly_window)
            weekly_kwargs = {
                "weekly_ema_13": weekly_ema_13_full.iloc[:weekly_window_length],
                "weekly_ema_26": weekly_ema_26_full.iloc[:weekly_window_length],
                "weekly_histogram": weekly_histogram_full.iloc[:weekly_window_length],
            }
        results.append(
            (
                bar_date,
                analyse(
                    ticker,
                    daily_ohlcv.iloc[: i + 1],
                    weekly_window,
                    ema_13=ema_13_full.iloc[: i + 1],
                    ema_26=ema_26_full.iloc[: i + 1],
                    histogram=histogram_full.iloc[: i + 1],
                    stochastic_k=stochastic_k_full.iloc[: i + 1],
                    force_index_2ema=force_index_2ema_full.iloc[: i + 1],
                    channel_upper=channel_upper_full.iloc[: i + 1],
                    channel_lower=channel_lower_full.iloc[: i + 1],
                    _daily_ohlcv_already_clean=True,
                    **weekly_kwargs,
                ),
            )
        )
    return results
