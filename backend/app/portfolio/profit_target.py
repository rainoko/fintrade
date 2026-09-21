"""Suggested profit target + reward:risk ratio for a fresh BUY signal (Elder ch. 53 "How to
Set Profit Targets" plus ch. 58's Tradebill formula -- docs/ideas.md, docs/Analyse.md §7). See
the `backend-profit-target` task's `decisions` entry for the full rationale behind every
judgment call below (BUY-only scope, target-source selection, endpoint placement), and the
`backend-profit-target-weekly-channel` task's `decisions` entry for the weekly-vs-daily
channel-timeframe correction below.

Two of Elder's three style-dependent target techniques are implemented here (the third -- a
day-trade's first-sign-of-opposing-divergence exit -- is explicitly out of this app's scope,
same as docs/ideas.md's own note, since this app has no intraday/day-trade use case):

- **Swing-style**: ch. 58's own explicit Tradebill formula for an "A" target -- current price
  + 30% of a channel height (`app.indicators.autoenvelope`, docs/Analyse.md §4) -- the same 30%
  figure the A-trade grading rubric (`app.portfolio.grading`) already uses for a
  >=30%-of-channel-height capture, by design (docs/ideas.md's own cross-reference). Ch. 39
  p.161 ("Stops and Profit Targets"), read directly: "Triple Screen calls for setting profit
  targets using long-term charts and stops on the charts of your intermediate timeframe... When
  buying a dip on a daily chart, the value zone on a weekly chart presents a good target." This
  app's intermediate timeframe is daily (Wave/Screen 2) and long-term is weekly (Tide/Screen
  1) -- so the channel height here is computed from the **weekly** chart's own Autoenvelope
  band (`weekly_ohlcv`, below), NOT the daily `channel_upper`/`channel_lower` this same ticker's
  `indicators` response reports alongside it (that pair stays daily -- it feeds the price-chart
  overlay and the entry-day trade-grading formula, both explicitly daily per docs/Analyse.md §4
  Row 6, and is a fully independent computation from what this module derives here). The
  protective stop below stays on daily data per that same ch. 39 rule -- it is the
  intermediate-timeframe half of the split and was already correct before this distinction was
  drawn out explicitly.
- **Position-style**: the nearest prior support/resistance level above current price
  (`app.signals.support_resistance`, docs/Analyse.md §4 row 9) -- stays daily; ch. 39's
  long-term-chart rule is specifically about the "value zone" (channel) target, not this
  technique, and `app.signals.support_resistance` has no weekly variant.

This app has no separate notion of "trade style" anywhere (no swing-vs-position distinction is
tracked for a fresh signal) -- rather than inventing one, both techniques are always computed
and the TIGHTER (closer-to-current-price) of the two candidates is used: a closer target is the
more conservative, more probable one to actually be reached, and this app already defaults to
the more conservative choice wherever Elder's own text leaves a range rather than a single
number (e.g. docs/Analyse.md §7's SafeZone coefficient uses the book's stated 2x minimum, not a
wider multiple).

BUY-only: this app's protective-stop formula (`app.portfolio.risk.stop_from_price_action`,
which this module calls to get a risk distance) is explicitly long-only, with no symmetric
short-side stop formula anywhere in the app to pair with a SELL-side reward:risk ratio -- see
that module's own comments and the `backend-safezone-stop-coefficient-fix` task's `decisions`
entry (a future short-position feature would need its own short-side stop coefficient before a
SELL-side profit target/reward:risk ratio could be computed the same way).
"""

import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.indicators.autoenvelope import autoenvelope
from app.portfolio.risk import stop_from_price_action, validate_daily_ohlcv_columns
from app.signals.support_resistance import Zone

TargetSource = Literal["channel", "support_resistance"]

# Elder ch. 58's own Tradebill formula for an "A" target: entry price + 30% of the channel
# height -- the same 30% figure the A-trade grading rubric already uses for a
# >=30%-of-channel-height capture (docs/Analyse.md §7, `app.portfolio.grading`), by design.
_TRADEBILL_CHANNEL_FRACTION = 0.30

# The Autoenvelope's own standard EMA period (docs/Analyse.md §4 Row 6: "EMA 13 +/- avg %
# deviation") -- used here for the WEEKLY channel this module computes (see this module's own
# docstring for why weekly, per ch. 39 p.161), same period as every other daily use of the
# Autoenvelope elsewhere in the app (`app.signals.engine`'s `channel_upper`/`channel_lower`,
# `app.portfolio.grading`'s entry-day channel height). `deviation_lookback` is left at
# `autoenvelope`'s own default (100 bars -- 100 WEEKS here, not 100 days) rather than a
# separate weekly-specific constant: nothing in docs/Analyse.md or Elder's own text calls for a
# different lookback just because the bar interval changed, and reusing one already-documented
# default avoids inventing an unexplained second number.
_CHANNEL_EMA_PERIOD = 13

# "Potential reward should be at least 2x the risk" -- Elder's own explicit minimum
# (docs/ideas.md ch. 53: "it seldom pays to risk a dollar to make a dollar").
_MIN_REWARD_RISK_RATIO = 2.0


@dataclass(frozen=True)
class ProfitTarget:
    """One suggested target for a fresh BUY signal, plus the reward:risk ratio it implies
    against the ticker's current protective-stop distance. See `suggest_profit_target`'s own
    docstring for how each field is derived."""

    price: float
    source: TargetSource
    distance_to_stop: float
    distance_to_target: float
    reward_risk_ratio: float | None
    meets_minimum_reward_risk: bool


def _nearest_resistance_price(zones: list[Zone], current_price: float) -> float | None:
    """The nearest zone edge strictly above `current_price` across all `zones` -- Elder's own
    "nearest prior support/resistance level above current price" (docs/ideas.md ch. 53).

    Filters by each zone's own price POSITION relative to `current_price`, not by its `role`
    label (`support`/`resistance`) -- `role` tracks which side of a past breakout a zone
    currently sits on, a related but distinct concept from "is this level above price right
    now" (see the `backend-profit-target` task's `decisions` entry for why position, not role,
    is what's checked here -- in practice the two coincide for almost every zone, since a role
    flip only ever happens once price has already moved past the zone, but this function
    doesn't rely on that coincidence).

    Uses each qualifying zone's `lower` edge (the first price level reached climbing toward it
    from below) as the target, not its midpoint or upper edge -- mirroring the same
    near-the-edge-not-the-middle convention `Zone.false_breakout.extreme_price` already
    established for this type. Returns `None` if no zone qualifies.
    """
    above = [zone.lower for zone in zones if zone.lower > current_price]
    return min(above) if above else None


def _weekly_channel_bounds(weekly_ohlcv: pd.DataFrame) -> tuple[float, float] | None:
    """The latest upper/lower Autoenvelope channel bounds computed from `weekly_ohlcv`'s own
    `close` series -- Elder ch. 39 p.161's "the value zone on a weekly chart presents a good
    target" (see this module's own docstring for the full timeframe rationale). Computed fresh
    here rather than reusing `app.signals.engine.analyse`'s `result.indicators["channel_upper"/
    "channel_lower"]`, since that pair is a DAILY Autoenvelope pass (feeds the price-chart
    overlay and entry-day trade grading, both explicitly daily) -- a different computation from
    what this weekly target needs, not an interchangeable one.

    Returns `None` (treated as "channel unavailable", the candidate simply skipped, not
    fabricated) if `weekly_ohlcv` is empty, lacks a `close` column, or the Autoenvelope's own
    ~100-WEEK average-deviation warm-up window isn't yet full at the latest bar (a `nan` band,
    same warm-up condition `app.signals.engine.analyse` already documents for the daily
    channel, just measured in weeks here instead of days).
    """
    if weekly_ohlcv.empty or "close" not in weekly_ohlcv.columns:
        return None
    bands = autoenvelope(weekly_ohlcv["close"], ema_period=_CHANNEL_EMA_PERIOD)
    upper = float(bands["upper"].iloc[-1])
    lower = float(bands["lower"].iloc[-1])
    if not (math.isfinite(upper) and math.isfinite(lower)):
        return None
    return upper, lower


def suggest_profit_target(
    daily_ohlcv: pd.DataFrame,
    zones: list[Zone],
    *,
    weekly_ohlcv: pd.DataFrame,
    short_ema: pd.Series | None = None,
) -> ProfitTarget | None:
    """A suggested profit target + reward:risk ratio for a FRESH BUY signal on `daily_ohlcv`
    (already cleaned of malformed bars via `app.signals.engine.drop_malformed_daily_bars`,
    most-recent bar last). See this module's docstring for why this is BUY-only.

    `weekly_ohlcv` is this same ticker's weekly OHLCV (most-recent bar last, the same frame
    passed to `app.signals.engine.analyse`'s own `weekly_ohlcv` parameter) -- used here ONLY to
    compute the weekly Autoenvelope channel this target's "Tradebill" candidate is derived from
    (`_weekly_channel_bounds`, above), per ch. 39 p.161's explicit long-term-chart rule (see
    this module's own docstring). This is a fresh computation, not a passthrough of any other
    already-computed value -- unlike `zones` below, nothing else in this app currently needs a
    weekly Autoenvelope pass to share it with. An empty or too-short `weekly_ohlcv` (rare in
    production, since `GET /api/stocks/{ticker}/analysis` already requires >=26 weeks of weekly
    history to reach this call at all) degrades the same way a `nan`/unavailable channel always
    has here: the channel-based candidate is simply skipped, not fabricated from a partial
    window.

    `zones` should be `app.signals.support_resistance.detect_support_resistance_zones`'s
    already-computed output for this same `daily_ohlcv` -- the caller (`get_analysis`) already
    computes this once for `AnalysisResponse.support_resistance_zones`, reused here rather than
    running a second, redundant whole-history detection pass. This candidate stays daily -- ch.
    39's long-term-chart rule is specifically about the channel/value-zone target, not this
    technique (see this module's own docstring).

    Picks whichever of the two candidate prices (channel-derived, support/resistance-derived)
    is CLOSER to current price -- see this module's own docstring for why the tighter one wins
    rather than a fixed preference order. Then computes:

    - `distance_to_stop`: current price minus `app.portfolio.risk.stop_from_price_action`'s
      long-only SafeZone stop for this same `daily_ohlcv` (docs/Analyse.md §7) -- the trade's
      per-share risk if entered at current price. Can be <= 0 in the rare case current price is
      already at or below that stop.
    - `distance_to_target`: the chosen target price minus current price -- the trade's
      per-share potential reward. Non-negative by construction (both candidate techniques only
      ever produce a price at or above current price) -- strictly positive for every realistic
      input, but not a strict invariant the code actually enforces: the channel-derived target
      degenerates to exactly current price (`distance_to_target == 0`) in the fully degenerate
      case where the weekly Autoenvelope's rolling average deviation is exactly 0 across the
      whole lookback window (upper == lower).
    - `reward_risk_ratio`: `distance_to_target / distance_to_stop`, or `None` when
      `distance_to_stop <= 0` (an undefined ratio, not a fabricated number).
    - `meets_minimum_reward_risk`: whether `reward_risk_ratio >= 2.0`, Elder's own explicit
      minimum ("it seldom pays to risk a dollar to make a dollar", docs/ideas.md ch. 53).
      `False` (never left ambiguous) when `reward_risk_ratio` itself is `None` -- an undefined
      ratio can't meet the bar either. This is the explicit "flag, don't silently hide" signal
      docs/ideas.md calls for, not something a client has to derive itself from the raw ratio.

    Returns `None` if `daily_ohlcv` is empty, or if NEITHER technique produces a candidate
    target (no weekly channel bounds available AND no qualifying zone above current price) -- a
    real, unremarkable case (e.g. a young ticker with under ~100 weeks of weekly history and no
    yet-detected resistance zone above it), not an error.

    Raises:
        ValueError: if `daily_ohlcv` is non-empty but missing a required column (`low`/
            `close`) -- validated up front via `app.portfolio.risk
            .validate_daily_ohlcv_columns`, the same check `stop_from_price_action` itself
            would otherwise run, so a malformed-but-non-empty frame fails here with this
            documented error before `current_price`'s own `daily_ohlcv["close"]` read below
            ever runs (previously that read could raise a bare `KeyError` instead, for a frame
            missing `close` specifically -- see this task's `decisions` entry).
    """
    if daily_ohlcv.empty:
        return None
    validate_daily_ohlcv_columns(daily_ohlcv)
    current_price = float(daily_ohlcv["close"].iloc[-1])

    candidates: list[tuple[float, TargetSource]] = []
    channel_bounds = _weekly_channel_bounds(weekly_ohlcv)
    if channel_bounds is not None:
        channel_upper, channel_lower = channel_bounds
        channel_height = channel_upper - channel_lower
        candidates.append(
            (current_price + _TRADEBILL_CHANNEL_FRACTION * channel_height, "channel")
        )
    sr_price = _nearest_resistance_price(zones, current_price)
    if sr_price is not None:
        candidates.append((sr_price, "support_resistance"))
    if not candidates:
        return None

    # The TIGHTER (closer to current price) candidate wins -- see this module's own docstring.
    price, source = min(candidates, key=lambda candidate: abs(candidate[0] - current_price))

    # columns_validated=True: validate_daily_ohlcv_columns(daily_ohlcv) above already checked
    # the identical low/close requirement -- avoids a redundant second pass, mirroring
    # app.portfolio.exits.evaluate_exit_flags's own convention.
    stop = stop_from_price_action(daily_ohlcv, short_ema=short_ema, columns_validated=True)
    distance_to_stop = current_price - stop
    distance_to_target = price - current_price
    reward_risk_ratio = distance_to_target / distance_to_stop if distance_to_stop > 0 else None
    meets_minimum_reward_risk = (
        reward_risk_ratio is not None and reward_risk_ratio >= _MIN_REWARD_RISK_RATIO
    )

    return ProfitTarget(
        price=price,
        source=source,
        distance_to_stop=distance_to_stop,
        distance_to_target=distance_to_target,
        reward_risk_ratio=reward_risk_ratio,
        meets_minimum_reward_risk=meets_minimum_reward_risk,
    )
