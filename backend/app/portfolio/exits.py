import pandas as pd

from app.indicators.autoenvelope import autoenvelope
from app.portfolio.models import Account, Position
from app.portfolio.risk import position_risk_pct, protective_stop
from app.signals.impulse import evaluate_impulse
from app.signals.triple_screen import evaluate_tide

# 2% rule threshold: a position's *own* current risk exceeding this is flagged
# (docs/Analyse.md §7). Matches the strict ">" used by risk.py's own tests
# (e.g. test_oversized_position_exceeds_two_percent).
_TWO_PERCENT_RULE_THRESHOLD = 2.0

# 6% rule threshold: the *portfolio's* total open risk exceeding this makes every
# position with nonzero current risk a contributor (docs/Analyse.md §7).
_SIX_PERCENT_RULE_THRESHOLD = 6.0


def evaluate_exit_flags(
    position: Position,
    account: Account,
    daily_ohlcv: pd.DataFrame,
    weekly_ohlcv: pd.DataFrame,
    portfolio_open_risk_pct: float,
) -> list[str]:
    """Existing-position exit conditions, independent of fresh-entry signal logic (docs/Analyse.md §7).

    Possible flags (order below is the order they're evaluated/appended in; a position can
    carry any subset, including none):

    - ``'stop_hit'``: today's close is below the protective stop *in force as of today* --
      ``protective_stop(position, daily_ohlcv[:-1])``, i.e. computed from history strictly
      *before* today's bar, then compared against today's close (docs/Analyse.md §7's "close
      below this stop is itself a SELL trigger ... regardless of Screen 2/3 state"). This is
      deliberately *not* ``protective_stop(position, daily_ohlcv)`` (today included) -- see
      this task's `decisions` entry: since ``protective_stop``'s swing low is a `min()` over
      its window, it can never exceed today's own low, and close >= low always holds for a
      single bar, so a today-inclusive stop can *never* be breached by today's own close (the
      "breach" would require close < swing_low <= today's low <= close, a contradiction).
      Real protective stops work by being set from prior data and then watched against the
      next close, not recomputed from a window that already includes the very close being
      tested.
    - ``'two_percent_rule_breached'``: this position's *own* current risk (``risk.
      position_risk_pct``, against that same as-of-today stop) exceeds 2% of account equity --
      "position has grown/equity has shrunk" per §7, evaluated off current price/equity, never
      entry-time values.
    - ``'six_percent_rule_contributor'``: the portfolio's total open risk (
      ``portfolio_open_risk_pct``, i.e. ``risk.total_open_risk_pct()`` computed by the caller
      across every position -- this function only has this one position's own OHLCV, so the
      portfolio-wide sum can't be recomputed here) exceeds 6%, *and* this position still has
      nonzero current risk (a position that already hit its stop has zero forward risk left
      to contribute -- see 'stop_hit' above and risk.py's own floor-at-zero rationale). See
      this task's `decisions` entry for why ``portfolio_open_risk_pct`` is a parameter here
      rather than something this function derives on its own.
    - ``'profit_zone_impulse_red'``: today's close is at/above the upper Autoenvelope band
      (``app.indicators.autoenvelope``, EMA(13) ± avg % deviation, the app's standard
      profit-target channel per docs/Analyse.md §4) *and* today's Impulse
      (``app.signals.impulse.evaluate_impulse``) is RED -- "price reaches the upper
      Autoenvelope/channel band with Impulse turning Red" per §7. Evaluated as a plain
      current-state test (today's Impulse *is* RED while price sits at/above the band), not a
      same-day transition from a prior non-RED bar -- see this task's `decisions` entry for
      why "turning" is read that way here (in contrast to 'tide_flipped_bearish' below, which
      *is* implemented as an explicit transition).
    - ``'tide_flipped_bearish'``: the weekly Tide (``app.signals.triple_screen.evaluate_tide``)
      is BEARISH as of the latest weekly bar but was BULLISH as of the prior weekly bar --
      §7's literal "flips from BULLISH to BEARISH" (this app is long-only, so every position
      is implicitly "currently long" -- see risk.py's ``protective_stop`` docstring).

    None of these are gated by, or suppress, a fresh-entry HOLD/BUY/SELL from
    ``app.signals.engine.analyse`` -- this function doesn't take a signal as input at all, by
    design, per the verify-elder-signal Portfolio Risk Overlay checklist ("existing-position
    exit flags are evaluated independently of the fresh-entry signal logic -- a HOLD signal
    must not suppress a stop-hit or 6%-rule-breach exit flag").

    ``daily_ohlcv``/``weekly_ohlcv`` are this position's own OHLCV history (not the whole
    account's) -- same shape/ordering contract as ``app.portfolio.risk.protective_stop``
    (lowercase columns, most recent row last). ``daily_ohlcv`` must have at least 2 rows
    (yesterday, to seed the stop, plus today, to test against it) -- a 1-row or empty
    ``daily_ohlcv`` raises via ``protective_stop`` on the resulting empty ``[:-1]`` slice, same
    as that function's own empty-input ValueError. ``weekly_ohlcv`` degrades gracefully to no
    'tide_flipped_bearish' flag on short history, mirroring ``evaluate_tide``'s own <2-row
    NEUTRAL fallback.

    Raises:
        ValueError: propagated from ``protective_stop`` (``daily_ohlcv`` with fewer than 2
            rows, or malformed) or ``position_risk_pct`` (``position.current_price`` unset,
            non-positive account equity) -- this function adds no additional validation of its
            own beyond what those two already enforce.
    """
    flags: list[str] = []

    # Stop "in force" as of today: history strictly before today's bar (see the 'stop_hit'
    # bullet above for why today's own bar must be excluded here).
    stop = protective_stop(position, daily_ohlcv.iloc[:-1])
    latest_close = float(daily_ohlcv["close"].iloc[-1])
    if latest_close < stop:
        flags.append("stop_hit")

    risk_pct = position_risk_pct(position, stop, account)
    if risk_pct > _TWO_PERCENT_RULE_THRESHOLD:
        flags.append("two_percent_rule_breached")
    if portfolio_open_risk_pct > _SIX_PERCENT_RULE_THRESHOLD and risk_pct > 0.0:
        flags.append("six_percent_rule_contributor")

    upper_band = autoenvelope(daily_ohlcv["close"])["upper"].iloc[-1]
    if not pd.isna(upper_band) and latest_close >= upper_band and evaluate_impulse(daily_ohlcv) == "RED":
        flags.append("profit_zone_impulse_red")

    current_tide = evaluate_tide(weekly_ohlcv).trend
    previous_tide = evaluate_tide(weekly_ohlcv.iloc[:-1]).trend
    if previous_tide == "BULLISH" and current_tide == "BEARISH":
        flags.append("tide_flipped_bearish")

    return flags
