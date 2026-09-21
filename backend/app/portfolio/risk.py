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


# Ch. 54's "Don't Let a Winning Trade Turn into a Loss" subsection (docs/ideas.md's ch. 54
# entry) -- unrealized profit, as a fraction of entry price, that must be reached before the
# trailing/profit-protecting stop "cuffs the trade" to breakeven at all. Elder states the
# *behavior* (move to breakeven once profit has grown enough to afford it, without giving a
# number) but not a specific trigger threshold -- 10% is this app's own judgment call: large
# enough that ordinary daily noise on a swing-timeframe position won't false-trigger it long
# before a real trend move has developed, small enough that a genuinely winning trade isn't
# left unprotected for too long. See this task's (backend-trailing-profit-stop) `decisions`
# entry for the alternatives considered (a fixed dollar/point amount, or a multiple of the
# position's own risk-to-stop distance -- both rejected as less simple to reason about/test
# than a plain percent-of-entry-price figure).
_TRAILING_STOP_BREAKEVEN_TRIGGER_PCT = 0.10

# Elder's own worked example for the fraction of ADDITIONAL profit (the portion earned beyond
# the breakeven trigger above) the stop protects once "cuffed" -- explicitly called out in the
# book as an illustrative example, not a stated rule (docs/ideas.md's ch. 54 entry: "a growing
# fraction (Elder's own example: a third)"). Reused verbatim rather than picked independently,
# since it's the one concrete number the book actually gives for this mechanic.
_TRAILING_STOP_PROFIT_PROTECTION_FRACTION = 1.0 / 3.0


def trailing_profit_stop(entry_price: float, current_price: float, safezone_stop: float) -> float:
    """Elder ch. 54 "Don't Let a Winning Trade Turn into a Loss": as unrealized profit grows,
    move the stop to breakeven ("cuffing the trade") once profit crosses a threshold, then
    keep protecting a growing fraction of profit earned beyond that point as it increases
    further. A **single point-in-time** computation -- no memory of any earlier call -- see
    `ratchet_trailing_profit_stop` below for the stateless hard-ratchet wrapper that's actually
    wired into GET /api/portfolio/risk; this function is its per-day building block, factored
    out for direct, hand-computable unit testing.

    Long-only, mirroring `protective_stop`.

    - Below `_TRAILING_STOP_BREAKEVEN_TRIGGER_PCT` unrealized profit (as a fraction of
      ``entry_price``): returns ``safezone_stop`` verbatim -- this mechanic doesn't exist yet
      for a trade that hasn't earned enough profit to be worth protecting; the ordinary
      volatility-based SafeZone stop applies unchanged.
    - At or above that threshold: returns
      ``entry_price + _TRAILING_STOP_PROFIT_PROTECTION_FRACTION * (profit beyond the
      threshold)`` -- exactly ``entry_price`` (breakeven) the instant the threshold is first
      reached (zero profit beyond it yet), then rising continuously as profit grows further.
      Applying the fraction to profit *beyond* the trigger (not total profit) is what makes
      "crosses the threshold" and "moves to breakeven" the same event with no discontinuity --
      see this task's `decisions` entry for the alternative (fraction of *total* profit)
      considered and rejected because it would already be above breakeven at the moment of
      crossing, contradicting the book's own "cuffing" framing.
    - Deliberately does **not** re-involve ``safezone_stop`` once the threshold is crossed:
      see `ratchet_trailing_profit_stop`'s own docstring for why a live, independently-
      fluctuating SafeZone value can't safely participate in a value that has to never
      decrease.

    Raises:
        ValueError: if ``entry_price`` isn't positive.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive to compute a trailing profit stop")

    profit = current_price - entry_price
    threshold_profit = entry_price * _TRAILING_STOP_BREAKEVEN_TRIGGER_PCT
    if profit < threshold_profit:
        return safezone_stop

    profit_beyond_threshold = profit - threshold_profit
    return entry_price + _TRAILING_STOP_PROFIT_PROTECTION_FRACTION * profit_beyond_threshold


def ratchet_trailing_profit_stop(
    position: Position,
    daily_ohlcv: pd.DataFrame,
    safezone_stop: float,
    *,
    persisted_high_water_mark: float | None = None,
) -> float:
    """The actual, stateful-in-effect trailing/profit-protecting stop wired into GET
    /api/portfolio/risk (`RiskPosition.trailing_stop`) -- a **hard ratchet**: once returned,
    never lower than any value this same function has ever returned for this position before
    (Elder ch. 54's companion "Move Your Stop Only in the Direction of Your Trade").

    Two layers work together to make that guarantee actually hold:

    1. A **stateless recomputation over this position's full price history**: `daily_ohlcv` is
       the same full-available-history frame every other caller in this endpoint already has in
       hand (`app.data.base.DataProvider.get_daily_ohlcv` fetches "full available history", per
       its own docstring), so folding `trailing_profit_stop` over every close from
       ``position.entry_date`` through today and taking the running max reconstructs, on its
       own, everything a persisted ratchet would have accumulated *for a fixed cost basis*: new
       bars only ever get appended, never revised away, and the folded quantity depends only on
       ``entry_price`` (== ``position.avg_cost_basis``) and immutable past closes, so extending
       the fold with new bars alone can only hold the result steady or raise it.
    2. A **persisted high-water mark floor** (``persisted_high_water_mark``, backed by
       ``PositionORM.trailing_stop_high_water_mark``): the caller passes in the highest value
       this function has ever returned for this position before, and this function returns
       ``max(<freshly recomputed candidate>, persisted_high_water_mark)`` -- never lower than
       that floor, regardless of what the fresh recompute alone would say.

    Layer 2 exists because layer 1 *alone* is not actually safe against `POST
    /api/portfolio/positions`'s same-ticker merge, which can raise `avg_cost_basis` (a
    quantity-weighted average) with **no price movement at all**. That merge changes
    ``entry_price`` for every future call, which changes `threshold_profit` (`entry_price *
    _TRAILING_STOP_BREAKEVEN_TRIGGER_PCT`) and the breakeven point itself (`entry_price` is
    the additive base of `trailing_profit_stop`'s formula) -- so a historical close that
    qualified (and set the high-water mark) under the OLD, lower cost basis can silently stop
    qualifying (or produce a lower candidate) once recomputed under the NEW, higher one,
    letting the *reported* value decrease even though the stateless fold, taken alone, never
    mis-evaluates any individual call. This exact scenario (entered at $100, rallied to $115,
    ratcheted to ~$101.667; then merged with a buy at $200 with no further price change,
    raising `avg_cost_basis` to $150) was caught by PR review against this task's original
    all-stateless design -- see this task's (backend-trailing-profit-stop) `decisions` entry
    for the full history: a persisted column was considered and rejected there for exactly this
    kind of avg_cost_basis-changing merge, without realizing the chosen stateless alternative
    had the identical defect via a different mechanism. `PositionORM
    .trailing_stop_high_water_mark` is written back by `app.api.routers.portfolio.get_risk` as
    `max(existing persisted value, this function's return value)` every call, making
    `GET /api/portfolio/risk` this codebase's first side-effecting-write GET route -- an
    accepted, narrow deviation once the purely-stateless alternative was shown not to actually
    satisfy the "never decreases" contract this field's own schema description promises.

    `safezone_stop` (today's live, independently -- and non-monotonically -- fluctuating
    SafeZone value) is deliberately used only as a *pre-trigger* pass-through (matching
    `trailing_profit_stop`'s own single-call contract) and never re-folded into the ratchet
    once triggered -- letting a currently-lower live `safezone_stop` back into the post-trigger
    max would reopen exactly the "could decrease later" gap this whole function exists to
    close. A position whose profit has never crossed the trigger, and which has no persisted
    high-water mark yet either, simply passes `safezone_stop` straight through unchanged,
    matching `protective_stop`'s own free-to-move-either-way behavior -- there's no "winning
    trade" yet for this mechanic to protect.

    ``position.entry_date`` rows with a NaN close are skipped (can't inform the ratchet either
    way). If no row in ``daily_ohlcv`` is on or after ``position.entry_date`` at all (a
    malformed/incomplete history that doesn't reach back to entry -- see
    `app.portfolio.grading.grade_trade_from_filtered_history`'s identical concern), the whole
    frame is used instead of raising, since a stop somewhat too conservative (ignoring
    genuinely-pre-entry bars can only ever be MORE conservative here, never less, given the
    ratchet is a `max`) is preferable to excluding the position from `positions` entirely over
    a data-completeness gap unrelated to whether a stop can be computed at all.

    ``persisted_high_water_mark``, if given, floors the result at that value (see layer 2
    above); omit it (the default, `None`) for a position with no persisted value yet (e.g. its
    first-ever call, or a test exercising the stateless fold in isolation) -- behaves exactly as
    the original all-stateless implementation did.

    Raises:
        ValueError: if ``daily_ohlcv`` is empty or missing a ``close`` column, or if
            ``position.avg_cost_basis`` isn't positive (mirrors `trailing_profit_stop`'s own
            precondition).
    """
    if daily_ohlcv.empty:
        raise ValueError("daily_ohlcv must contain at least one row to compute a trailing stop")
    if "close" not in daily_ohlcv.columns:
        raise ValueError("daily_ohlcv is missing required column: 'close'")
    if position.avg_cost_basis <= 0:
        raise ValueError("entry_price must be positive to compute a trailing profit stop")

    # `daily_ohlcv.index` is a real `pd.DatetimeIndex` for every genuine `DataProvider` frame
    # (see `stop_from_price_action`'s own column-shape reference), but a caller-constructed
    # test fixture can hand this a plain `RangeIndex` (e.g. a `pd.concat(..., ignore_index=
    # True)`) -- comparing a non-datetime index against a `pd.Timestamp` raises `TypeError`
    # rather than returning a useless-but-harmless all-False mask, so that case (like the "no
    # row on/after entry_date at all" case below) falls back to using the whole frame instead
    # of raising.
    if isinstance(daily_ohlcv.index, pd.DatetimeIndex):
        since_entry = daily_ohlcv.loc[daily_ohlcv.index >= pd.Timestamp(position.entry_date)]
    else:
        since_entry = daily_ohlcv
    if since_entry.empty:
        since_entry = daily_ohlcv

    entry_price = position.avg_cost_basis
    threshold_profit = entry_price * _TRAILING_STOP_BREAKEVEN_TRIGGER_PCT
    ratcheted: float | None = None
    for close in since_entry["close"]:
        if pd.isna(close):
            continue
        # Whether *this specific day* ever triggered is checked directly against the same
        # profit/threshold comparison `trailing_profit_stop` itself makes -- not inferred by
        # comparing its return value to `safezone_stop`, which could coincidentally match a
        # genuinely post-trigger candidate and wrongly exclude it from the ratchet.
        if (float(close) - entry_price) < threshold_profit:
            continue
        candidate = trailing_profit_stop(entry_price, float(close), safezone_stop)
        ratcheted = candidate if ratcheted is None else max(ratcheted, candidate)

    fresh_candidate = safezone_stop if ratcheted is None else ratcheted
    if persisted_high_water_mark is None:
        return fresh_candidate
    return max(fresh_candidate, persisted_high_water_mark)


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
