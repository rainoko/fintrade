import pandas as pd

from app.indicators.autoenvelope import autoenvelope
from app.indicators.ema import ema
from app.indicators.macd import macd_components
from app.portfolio.models import Account, Position
from app.portfolio.risk import position_risk_pct, protective_stop, validate_daily_ohlcv_columns
from app.signals.impulse import evaluate_impulse
from app.signals.triple_screen import evaluate_tide, validate_weekly_ohlcv_columns

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

    Precondition -- ``daily_ohlcv`` and ``position.current_price`` must be as-of the *same*
    trading day (i.e. ``position.current_price`` reflects the same close ``daily_ohlcv['close']
    .iloc[-1]`` represents, not a stale/differently-timed price): this function takes them as
    two independent parameters and does *not* validate that they agree. When they do agree,
    'stop_hit' and 'six_percent_rule_contributor' can't both fire for the same position in the
    same call -- 'stop_hit' means today's close is below the stop, which floors this position's
    ``position_risk_pct`` (and so 'six_percent_rule_contributor', which requires nonzero risk)
    at 0, since both are evaluated against that same today's-close-derived stop and
    ``position.current_price``. If a caller ever passes a ``daily_ohlcv`` whose latest bar and
    ``position.current_price`` are out of sync (e.g. a stale cached price alongside a fresher
    OHLCV bar), that guarantee no longer holds and both flags could fire together -- this
    function has no way to detect that from its inputs alone, so keeping them in sync is the
    caller's responsibility. See the ``portfolio-exit-rules-followups`` task's `decisions` entry
    for why this is documented rather than enforced.

    Raises:
        ValueError: for a malformed ``daily_ohlcv`` (empty, or missing a required column) --
            validated up front via ``risk.validate_daily_ohlcv_columns``, the same check
            ``protective_stop`` itself enforces, run here first so this function's own
            ``daily_ohlcv['close']`` access (needed before ``protective_stop`` is called, to
            share EMA(13) across collaborators -- see above) can't raise a bare ``KeyError``
            instead; ``daily_ohlcv`` with fewer than 2 rows still raises from
            ``protective_stop`` on its ``.iloc[:-1]`` slice; for a ``weekly_ohlcv`` missing the
            ``close`` column (regardless of row count) -- validated via ``triple_screen
            .validate_weekly_ohlcv_columns`` before this function's own
            ``weekly_ohlcv['close']`` access, for the same reason as the daily-side check
            (``evaluate_tide`` runs the identical validation itself, but only once there are
            already >= 2 rows -- see its docstring -- so this function's own earlier, row-
            count-independent access needs its own guard too); or propagated from
            ``position_risk_pct`` (``position.current_price`` unset, non-positive account
            equity).
    """
    flags: list[str] = []

    # Validate daily_ohlcv's columns *before* this function's own daily_close = daily_ohlcv
    # ["close"] access below -- otherwise a malformed daily_ohlcv missing "close" would raise a
    # bare KeyError here instead of the documented ValueError that protective_stop (called
    # further down) would otherwise have raised first. See the portfolio-exit-rules-followups
    # task's `decisions` entry.
    validate_daily_ohlcv_columns(daily_ohlcv)

    # EMA(13) of the daily close, computed once over the full (today-inclusive) series and
    # shared -- via each function's optional precomputed-series parameter -- across
    # protective_stop (sliced to exclude today, below), autoenvelope, and evaluate_impulse,
    # which would otherwise each independently recompute an identical EMA(13) pass. Valid
    # because EMA is causal (a value at index t depends only on data up to t), so slicing this
    # full-series computation gives the same values as recomputing over a truncated series --
    # see the portfolio-exit-rules-followups task's `decisions` entry.
    daily_close = daily_ohlcv["close"]
    daily_ema_13 = ema(daily_close, 13)

    # Stop "in force" as of today: history strictly before today's bar (see the 'stop_hit'
    # bullet above for why today's own bar must be excluded here). columns_validated=True
    # because validate_daily_ohlcv_columns(daily_ohlcv) above already checked the identical
    # {'low', 'close'} column set on this same frame -- slicing rows via .iloc[:-1] can't
    # change which columns exist, so protective_stop's own column-membership re-check would
    # just repeat that work; it still checks .empty itself, since that's the one thing this
    # function's up-front validation (run before the slice) doesn't guarantee stays true after
    # it. See the portfolio-exit-rules-followups-followups task's `decisions` entry.
    stop = protective_stop(
        position,
        daily_ohlcv.iloc[:-1],
        short_ema=daily_ema_13.iloc[:-1],
        columns_validated=True,
    )
    latest_close = float(daily_close.iloc[-1])
    if latest_close < stop:
        flags.append("stop_hit")

    risk_pct = position_risk_pct(position, stop, account)
    if risk_pct > _TWO_PERCENT_RULE_THRESHOLD:
        flags.append("two_percent_rule_breached")
    if portfolio_open_risk_pct > _SIX_PERCENT_RULE_THRESHOLD and risk_pct > 0.0:
        flags.append("six_percent_rule_contributor")

    upper_band = autoenvelope(daily_close, mid=daily_ema_13)["upper"].iloc[-1]
    if (
        not pd.isna(upper_band)
        and latest_close >= upper_band
        and evaluate_impulse(daily_ohlcv, ema_13=daily_ema_13) == "RED"
    ):
        flags.append("profit_zone_impulse_red")

    # Validate weekly_ohlcv's columns *before* this function's own weekly_close =
    # weekly_ohlcv["close"] access below (guarded by the row-count check further down, but
    # this validation itself must run regardless of row count) -- same rationale as the
    # daily-side validate_daily_ohlcv_columns call above: a malformed weekly_ohlcv missing
    # "close" must raise the documented ValueError rather than a bare KeyError, even when
    # there are fewer than 2 rows (evaluate_tide's own internal validation is only reached
    # once len(weekly_ohlcv) >= 2 -- see its docstring). See the
    # portfolio-exit-rules-followups task's `decisions` entry.
    validate_weekly_ohlcv_columns(weekly_ohlcv)

    # Weekly MACD-Histogram + EMA(13)/EMA(26), and both evaluate_tide calls that consume them,
    # are only computed when weekly_ohlcv has at least 2 rows: with fewer than 2, evaluate_tide
    # short-circuits internally to NEUTRAL/'flat' without ever touching the
    # histogram/ema_13/ema_26 passed in (see its own `if len(weekly_ohlcv) < 2:` check) --
    # which in turn makes 'tide_flipped_bearish' unreachable below (it requires
    # previous_tide == "BULLISH", never true once both calls resolve to NEUTRAL) -- so this
    # guard skips computing and discarding that MACD/EMA(13)/EMA(26) work on every call with
    # short weekly history, mirroring evaluate_tide's own graceful degradation (see this
    # function's own docstring). See the portfolio-exit-rules-followups-followups task's
    # `decisions` entry.
    if len(weekly_ohlcv) >= 2:
        weekly_close = weekly_ohlcv["close"]
        weekly_macd = macd_components(weekly_close)
        weekly_ema_13 = ema(weekly_close, 13)

        current_tide = evaluate_tide(
            weekly_ohlcv,
            histogram=weekly_macd.histogram,
            ema_13=weekly_ema_13,
            ema_26=weekly_macd.ema_slow,
        ).trend
        previous_tide = evaluate_tide(
            weekly_ohlcv.iloc[:-1],
            histogram=weekly_macd.histogram.iloc[:-1],
            ema_13=weekly_ema_13.iloc[:-1],
            ema_26=weekly_macd.ema_slow.iloc[:-1],
        ).trend
        if previous_tide == "BULLISH" and current_tide == "BEARISH":
            flags.append("tide_flipped_bearish")

    return flags
