import pandas as pd

from app.indicators.ema import ema
from app.portfolio.models import Account, Position

# "Recent" swing low + volatility-buffer lookback, in trading days (~2 weeks).
# docs/Analyse.md §7 specifies the SafeZone-style concept but not exact
# parameters -- see this task's `decisions` entry in docs/tasks/portfolio-risk-rules.json.
_SWING_LOW_WINDOW_DAYS = 10

# The "short EMA" referenced by §7's stop-loss definition. The book's own SafeZone
# formula (Elder ch. 54, per docs/ideas.md) uses a 22-day EMA; this app instead reuses
# EMA(13), the same period already used as the app's standard trend-following EMA
# (Impulse gate, Elder-Ray, Autoenvelope -- docs/Analyse.md §4), for coherence with the
# rest of the app's indicator stack rather than introducing a second, SafeZone-only EMA
# period that would need its own separate warm-up/plumbing everywhere this value is
# shared (app.portfolio.exits, GET /api/portfolio/risk) -- a deliberate, re-affirmed
# deviation from the book's specific number, not an oversight. See this task's
# (backend-safezone-stop-coefficient-fix) `decisions` entry.
_VOLATILITY_EMA_PERIOD = 13

# SafeZone's own multiplier coefficient (Elder ch. 54, per docs/ideas.md): "placing your
# stop any closer [than 2x the Average Downside Penetration] would be self-defeating."
# 2.0 is the book's minimum for a long stop (his worked examples use 2-3x); this app
# always uses the minimum rather than a wider multiple, since a wider coefficient is a
# risk-tolerance dial the book leaves to the trader's own judgment, not something
# docs/Analyse.md specifies a value for. The book's short-side figure starts at 3.0
# ("shorting near the highs requires wider stops than buying near quiet, sold-out
# bottoms") -- not applied here since this app is long-only today (see protective_stop's
# own docstring); a future short-position feature should introduce its own
# `_SAFEZONE_SHORT_COEFFICIENT = 3.0` alongside this one rather than reusing it, per this
# task's `decisions` entry.
_SAFEZONE_COEFFICIENT = 2.0


def validate_daily_ohlcv_columns(daily_ohlcv: pd.DataFrame) -> None:
    """Raise if ``daily_ohlcv`` lacks the ``low``/``close`` columns ``protective_stop`` requires.

    Factored out of ``protective_stop`` so a caller that needs to touch ``daily_ohlcv`` columns
    of its own *before* calling ``protective_stop`` (e.g. ``app.portfolio.exits
    .evaluate_exit_flags``, which shares a precomputed EMA(13) of ``daily_ohlcv['close']`` across
    several collaborators) can validate first and preserve the same fail-fast ``ValueError``
    contract, instead of raising a bare ``KeyError`` from its own premature column access -- see
    the ``portfolio-exit-rules-followups`` task's `decisions` entry.

    Raises:
        ValueError: if ``daily_ohlcv`` is empty or missing a required column.
    """
    if daily_ohlcv.empty:
        raise ValueError("daily_ohlcv must contain at least one row to compute a protective stop")
    missing = {"low", "close"} - set(daily_ohlcv.columns)
    if missing:
        raise ValueError(f"daily_ohlcv is missing required column(s): {sorted(missing)}")


def stop_from_price_action(
    daily_ohlcv: pd.DataFrame,
    *,
    short_ema: pd.Series | None = None,
    columns_validated: bool = False,
) -> float:
    """The `Position`-independent core of `protective_stop` below -- everything that formula
    actually computes, since `position` itself is never read by the calculation (see
    `protective_stop`'s own docstring). Factored out so a caller with no `Position` to hand it
    (e.g. `app.portfolio.profit_target.suggest_profit_target`, computing a stop-distance for a
    ticker's fresh BUY signal rather than an already-held position) doesn't have to fabricate
    one just to satisfy a parameter the math never uses -- see the `backend-profit-target`
    task's `decisions` entry. `protective_stop` delegates to this function unchanged; every
    parameter/behavior/docstring detail below is identical to `protective_stop`'s own.

    Raises:
        ValueError: if ``daily_ohlcv`` is empty, or (when ``columns_validated`` is False)
            missing a required column.
    """
    if columns_validated:
        if daily_ohlcv.empty:
            raise ValueError(
                "daily_ohlcv must contain at least one row to compute a protective stop"
            )
    else:
        validate_daily_ohlcv_columns(daily_ohlcv)

    window = daily_ohlcv.tail(_SWING_LOW_WINDOW_DAYS)
    swing_low = float(window["low"].min())

    if short_ema is None:
        # Recomputes EMA(13) from scratch when no caller-supplied `short_ema` is passed --
        # e.g. `app.portfolio.profit_target.suggest_profit_target` never passes one today,
        # even though `app.signals.engine.analyse` already computes the identical EMA(13)
        # series moments earlier in that same request (as `result.indicators["ema_13"]`,
        # exposed only as a latest scalar, not the full series). Negligible cost at current
        # data sizes -- worth sharing via a `short_ema` argument (mirroring how
        # `app.portfolio.exits.evaluate_exit_flags` already accepts one) if `analyse()` ever
        # exposes the full series to callers. See
        # docs/tasks/backend-profit-target-followups.json's `decisions` entry.
        short_ema = ema(daily_ohlcv["close"], _VOLATILITY_EMA_PERIOD)
    downside_penetration = (short_ema - daily_ohlcv["low"]).clip(lower=0.0)
    volatility_buffer = float(downside_penetration.tail(_SWING_LOW_WINDOW_DAYS).mean())

    return swing_low - (_SAFEZONE_COEFFICIENT * volatility_buffer)


def protective_stop(
    position: Position,
    daily_ohlcv: pd.DataFrame,
    *,
    short_ema: pd.Series | None = None,
    columns_validated: bool = False,
) -> float:
    """Swing low minus a coefficient-multiplied volatility buffer (docs/Analyse.md §7,
    SafeZone concept, Elder ch. 54).

    Exact formula: ``stop = swing_low - (_SAFEZONE_COEFFICIENT * average_downside_penetration)``,
    i.e. ``swing_low - (2.0 * volatility_buffer)``.

    Long-only: this is the stop-loss for a long position.

    - Swing low: the lowest ``low`` over the most recent ``_SWING_LOW_WINDOW_DAYS``
      trading days.
    - Volatility buffer (Average Downside Penetration): the average "downside
      penetration" of a short EMA (EMA(13) of ``close``) over that same window -- i.e.
      for each day, how far the day's low fell *below* the EMA that day (0 on days it
      didn't), averaged across the window. A choppier/more volatile recent history
      produces a wider buffer; a quiet uptrend with no penetrations produces a buffer
      near 0.
    - Coefficient: the raw buffer above is multiplied by ``_SAFEZONE_COEFFICIENT``
      (2.0, the book's own stated minimum -- "placing your stop any closer would be
      self-defeating") before being subtracted from the swing low. Without this
      multiplier the stop sits inside the zone of ordinary market noise the buffer
      itself measures, which is exactly what SafeZone exists to avoid -- see this
      task's (backend-safezone-stop-coefficient-fix) `decisions` entry for the
      pre-fix state and why 2.0 (not a higher multiple) was chosen.

    ``position`` isn't used by the calculation itself (this app is long-only
    for now); it's kept in the signature for symmetry with
    ``position_risk_pct``/``evaluate_exit_flags`` and so a future short-position
    variant doesn't need a signature change.

    ``daily_ohlcv`` must have ``low`` and ``close`` columns (lowercase, matching
    ``app.db.models.OHLCVCacheORM``), most recent row last.

    ``short_ema``, if given, is used as the already-computed EMA(13) of
    ``daily_ohlcv['close']`` instead of recomputing it here -- it must be
    index-aligned with ``daily_ohlcv`` (same length, same row order). This lets a
    caller that already needs EMA(13) of this same close series for another
    purpose (e.g. ``app.portfolio.exits.evaluate_exit_flags``, which also feeds
    it to ``autoenvelope``/``evaluate_impulse``) compute it once and share it,
    instead of every caller independently re-deriving an identical EMA pass --
    see the ``portfolio-exit-rules-followups`` task's `decisions` entry. Omit it
    (the default) to have this function compute EMA(13) itself, unchanged from
    before this parameter existed.

    ``columns_validated``, if True, skips this function's own column-membership check (the
    ``{'low', 'close'} - set(columns)`` part of ``validate_daily_ohlcv_columns``) and only
    checks ``daily_ohlcv.empty`` -- for a caller that has already validated the identical
    column set on this same frame moments earlier, e.g. ``app.portfolio.exits
    .evaluate_exit_flags``, whose own up-front ``validate_daily_ohlcv_columns`` call covers
    ``daily_ohlcv`` before this function is called on a row-sliced view of it (slicing rows
    can't change which columns exist, so that earlier validation's column-membership result
    still holds here -- it's ``.empty`` that slicing *can* invalidate, e.g. a 1-row
    ``daily_ohlcv`` sliced to ``.iloc[:-1]``, which is why that check alone still always runs).
    Leave this False (the default) for a caller that invokes this function directly on a frame
    it hasn't pre-validated itself -- e.g. ``app.api.routers.portfolio.get_risk``, which relies
    on this function's own ``ValueError`` to catch and exclude a malformed frame -- see the
    ``portfolio-exit-rules-followups-followups`` task's `decisions` entry.

    Raises:
        ValueError: if ``daily_ohlcv`` is empty, or (when ``columns_validated`` is False)
            missing a required column.
    """
    return stop_from_price_action(
        daily_ohlcv, short_ema=short_ema, columns_validated=columns_validated
    )


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


def realized_losses_pct(account: Account, realized_losses_this_month: float) -> float:
    """`realized_losses_this_month` (a non-negative dollar sum of this calendar month's
    closed-trade losses) as a percentage of current account equity -- the first half of the
    book's *actual* 6% Rule formula (docs/Analyse.md §7; the book's own worked example --
    cross-checked in docs/ideas.md's ch. 51 note -- sums "the sum of your losses for the
    current month" AND "the risks in open trades". `total_open_risk_pct` above is the latter;
    this function is the former).

    Deliberately takes the already-summed dollar figure rather than a list of closed-trade
    rows or a DB session: this module has no DB dependency anywhere else (``Account``/
    ``Position`` are plain domain models, not ORM rows), and "this calendar month" requires a
    DB query against ``ClosedTradeORM`` (app/db/models.py) filtered by ``exit_date`` -- that
    query lives in the caller (``app.api.routers.portfolio._realized_losses_this_month_pct``)
    instead of here, and the caller sums this function's result with
    ``total_open_risk_pct``'s own -- see the backend-trade-history-table task's `decisions`
    entry for why this is a sibling function rather than a single function that would need to
    take on that DB dependency itself.

    Raises:
        ValueError: if `account.equity.total` isn't positive, mirroring
            `position_risk_pct`/`total_open_risk_pct`'s identical precondition.
    """
    if account.equity.total <= 0:
        raise ValueError("account.equity.total must be positive to compute a risk percentage")
    return (realized_losses_this_month / account.equity.total) * 100
