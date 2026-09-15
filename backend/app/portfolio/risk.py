import pandas as pd

from app.indicators.ema import ema
from app.portfolio.models import Account, Position

# "Recent" swing low + volatility-buffer lookback, in trading days (~2 weeks).
# docs/Analyse.md §7 specifies the SafeZone-style concept but not exact
# parameters -- see this task's `decisions` entry in docs/tasks/portfolio-risk-rules.json.
_SWING_LOW_WINDOW_DAYS = 10

# The "short EMA" referenced by §7's stop-loss definition. Reuses EMA(13),
# the same period already used as the app's standard trend-following EMA
# (Impulse gate, Elder-Ray, Autoenvelope -- docs/Analyse.md §4) rather than
# introducing a new, unrelated period just for this calculation.
_VOLATILITY_EMA_PERIOD = 13


def protective_stop(position: Position, daily_ohlcv: pd.DataFrame) -> float:
    """Swing low minus a volatility buffer (docs/Analyse.md §7, SafeZone concept).

    Long-only: this is the stop-loss for a long position.

    - Swing low: the lowest ``low`` over the most recent ``_SWING_LOW_WINDOW_DAYS``
      trading days.
    - Volatility buffer: the average "downside penetration" of a short EMA
      (EMA(13) of ``close``) over that same window -- i.e. for each day, how far
      the day's low fell *below* the EMA that day (0 on days it didn't), averaged
      across the window. A choppier/more volatile recent history produces a
      wider buffer; a quiet uptrend with no penetrations produces a buffer near 0.

    ``position`` isn't used by the calculation itself (this app is long-only
    for now); it's kept in the signature for symmetry with
    ``position_risk_pct``/``evaluate_exit_flags`` and so a future short-position
    variant doesn't need a signature change.

    ``daily_ohlcv`` must have ``low`` and ``close`` columns (lowercase, matching
    ``app.db.models.OHLCVCacheORM``), most recent row last.

    Raises:
        ValueError: if ``daily_ohlcv`` is empty or missing a required column.
    """
    if daily_ohlcv.empty:
        raise ValueError("daily_ohlcv must contain at least one row to compute a protective stop")
    missing = {"low", "close"} - set(daily_ohlcv.columns)
    if missing:
        raise ValueError(f"daily_ohlcv is missing required column(s): {sorted(missing)}")

    window = daily_ohlcv.tail(_SWING_LOW_WINDOW_DAYS)
    swing_low = float(window["low"].min())

    short_ema = ema(daily_ohlcv["close"], _VOLATILITY_EMA_PERIOD)
    downside_penetration = (short_ema - daily_ohlcv["low"]).clip(lower=0.0)
    volatility_buffer = float(downside_penetration.tail(_SWING_LOW_WINDOW_DAYS).mean())

    return swing_low - volatility_buffer


def position_risk_pct(position: Position, stop: float, account: Account) -> float:
    """Fraction of account equity at risk if `position` hits its protective stop (2% rule, docs/Analyse.md §7).

    Uses ``position.quantity`` and ``position.current_price`` (i.e. the
    position's size *now*) against ``account.equity.total`` (equity *now*) --
    never values frozen at entry time, per the verify-elder-signal Portfolio
    Risk Overlay checklist.

    Distance to stop is ``current_price - stop``, floored at 0: once price has
    already closed below the stop, there's no further *forward* risk down to
    that level left to report here (the stop-hit condition itself is an exit
    flag, evaluated in ``app.portfolio.exits``, not a risk percentage).

    Returns the risk as a percentage (e.g. ``1.8`` for 1.8% of equity), matching
    the `GET /api/portfolio/risk` contract in docs/architecture/API.md.

    Raises:
        ValueError: if ``position.current_price`` is unset (unknown current
            price makes "current risk" uncomputable) or ``account.equity.total``
            isn't positive.
    """
    if position.current_price is None:
        raise ValueError(
            "position.current_price is required to compute current risk "
            "(the 2% rule must use current price, not the entry-time cost basis)"
        )
    if account.equity.total <= 0:
        raise ValueError("account.equity.total must be positive to compute a risk percentage")

    distance_to_stop = max(position.current_price - stop, 0.0)
    risk_amount = position.quantity * distance_to_stop
    return (risk_amount / account.equity.total) * 100


def total_open_risk_pct(account: Account, stops: dict[str, float]) -> float:
    """Sum of position_risk_pct across all positions (6% rule, docs/Analyse.md §7).

    ``stops`` maps ``position.id`` (not ticker -- a portfolio could in principle
    hold more than one lot of the same ticker with different ids) to that
    position's precomputed ``protective_stop()`` value. A position in
    ``account.positions`` with no entry in ``stops`` is skipped (its risk isn't
    known/computable and is intentionally not defaulted to 0 or excluded via a
    silently-wrong guess).
    """
    total = 0.0
    for position in account.positions:
        if position.id not in stops:
            continue
        total += position_risk_pct(position, stops[position.id], account)
    return total
