"""Suggested profit target + reward:risk ratio for a fresh BUY signal (Elder ch. 53 "How to
Set Profit Targets" plus ch. 58's Tradebill formula -- docs/ideas.md, docs/Analyse.md §7). See
the `backend-profit-target` task's `decisions` entry for the full rationale behind every
judgment call below (BUY-only scope, target-source selection, endpoint placement).

Two of Elder's three style-dependent target techniques are implemented here (the third -- a
day-trade's first-sign-of-opposing-divergence exit -- is explicitly out of this app's scope,
same as docs/ideas.md's own note, since this app has no intraday/day-trade use case):

- **Swing-style**: ch. 58's own explicit Tradebill formula for an "A" target -- current price
  + 30% of that day's Autoenvelope/channel height (`app.indicators.autoenvelope`, docs/
  Analyse.md §4) -- the same 30% figure the A-trade grading rubric (`app.portfolio.grading`)
  already uses for a >=30%-of-channel-height capture, by design (docs/ideas.md's own
  cross-reference).
- **Position-style**: the nearest prior support/resistance level above current price
  (`app.signals.support_resistance`, docs/Analyse.md §4 row 9).

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

from app.portfolio.risk import stop_from_price_action, validate_daily_ohlcv_columns
from app.signals.support_resistance import Zone

TargetSource = Literal["channel", "support_resistance"]

# Elder ch. 58's own Tradebill formula for an "A" target: entry price + 30% of that day's
# channel height -- the same 30% figure the A-trade grading rubric already uses for a
# >=30%-of-channel-height capture (docs/Analyse.md §7, `app.portfolio.grading`), by design.
_TRADEBILL_CHANNEL_FRACTION = 0.30

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


def suggest_profit_target(
    daily_ohlcv: pd.DataFrame,
    zones: list[Zone],
    *,
    channel_upper: float | None,
    channel_lower: float | None,
    short_ema: pd.Series | None = None,
) -> ProfitTarget | None:
    """A suggested profit target + reward:risk ratio for a FRESH BUY signal on `daily_ohlcv`
    (already cleaned of malformed bars via `app.signals.engine.drop_malformed_daily_bars`,
    most-recent bar last). See this module's docstring for why this is BUY-only.

    `channel_upper`/`channel_lower` should be the same values `app.signals.engine.analyse`'s
    own `result.indicators["channel_upper"/"channel_lower"]` reports for this ticker (itself
    `app.indicators.autoenvelope.autoenvelope`) -- passed in rather than recomputed here,
    matching this app's existing precompute-and-share convention (see e.g.
    `app.portfolio.exits.evaluate_exit_flags`). During the Autoenvelope's own ~100-bar warm-up
    window, `analyse()`'s own dict reports these as a bare `float('nan')` (only the Pydantic
    `AnalysisResponse.indicators` schema layer coerces that to JSON `null` -- see
    `app.signals.engine._latest`), so this function treats `None` OR a non-finite value
    (`nan`/`inf`) as "channel unavailable" -- the channel-based ("Tradebill") target candidate
    is simply skipped in either case, not fabricated from a partial window.

    `zones` should be `app.signals.support_resistance.detect_support_resistance_zones`'s
    already-computed output for this same `daily_ohlcv` -- the caller (`get_analysis`) already
    computes this once for `AnalysisResponse.support_resistance_zones`, reused here rather than
    running a second, redundant whole-history detection pass.

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
      case where the Autoenvelope's rolling average deviation is exactly 0 across the whole
      lookback window (`channel_upper == channel_lower`).
    - `reward_risk_ratio`: `distance_to_target / distance_to_stop`, or `None` when
      `distance_to_stop <= 0` (an undefined ratio, not a fabricated number).
    - `meets_minimum_reward_risk`: whether `reward_risk_ratio >= 2.0`, Elder's own explicit
      minimum ("it seldom pays to risk a dollar to make a dollar", docs/ideas.md ch. 53).
      `False` (never left ambiguous) when `reward_risk_ratio` itself is `None` -- an undefined
      ratio can't meet the bar either. This is the explicit "flag, don't silently hide" signal
      docs/ideas.md calls for, not something a client has to derive itself from the raw ratio.

    Returns `None` if `daily_ohlcv` is empty, or if NEITHER technique produces a candidate
    target (no channel bounds available AND no qualifying zone above current price) -- a real,
    unremarkable case (e.g. a young ticker with under ~100 days of history and no yet-detected
    resistance zone above it), not an error.

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
    if (
        channel_upper is not None
        and channel_lower is not None
        and math.isfinite(channel_upper)
        and math.isfinite(channel_lower)
    ):
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
