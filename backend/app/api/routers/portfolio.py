import logging
import math
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import cast, get_args

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.api.schemas import (
    ClosedTradeOut,
    ClosedTradesResponse,
    Equity,
    ErrorDetail,
    ExitReasonOut,
    FollowUpReviewIn,
    PortfolioResponse,
    PositionIn,
    PositionOut,
    ProfitTargetOut,
    RiskPosition,
    RiskResponse,
    TradeApgarIn,
    TradeApgarOut,
    TradeApgarQuestionOut,
)
from app.data.base import DataProvider
from app.data.exceptions import (
    DataProviderError,
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.db.models import AccountORM, ClosedTradeORM, PositionORM
from app.db.session import get_db
from app.indicators.autoenvelope import autoenvelope
from app.portfolio.exits import evaluate_exit_flags
from app.portfolio.grading import TradeGrade, grade_trade_from_filtered_history, trade_letter_grade
from app.portfolio.models import Account, ExitReason
from app.portfolio.models import Equity as DomainEquity
from app.portfolio.pricing import (
    EnrichedPosition,
    enrich_positions_with_price,
    latest_close,
    positions_value,
)
from app.portfolio.profit_target import ProfitTarget, suggest_profit_target
from app.portfolio.risk import (
    position_risk_pct,
    protective_stop,
    realized_losses_pct,
    total_open_risk_pct,
)
from app.portfolio.trade_apgar import ImpulseColor, price_vs_value_zone, score_trade_apgar
from app.signals.engine import SignalResult, analyse, drop_malformed_daily_bars
from app.signals.impulse import evaluate_impulse
from app.signals.support_resistance import detect_support_resistance_zones
from app.time_utils import today, utcnow

logger = logging.getLogger(__name__)

# 2%/6% rule thresholds used by the display fields below (`two_percent_rule_breached`,
# `six_percent_rule_breached`) -- kept in sync by hand with the identical private constants
# in app.portfolio.exits (`_TWO_PERCENT_RULE_THRESHOLD`/`_SIX_PERCENT_RULE_THRESHOLD`), the
# same way exits.py's own constants are hand-kept in sync with docs/Analyse.md §7 rather than
# imported from app.portfolio.risk -- see this task's `decisions` entry.
_TWO_PERCENT_RULE_THRESHOLD = 2.0
_SIX_PERCENT_RULE_THRESHOLD = 6.0

# The "roughly two months ago" follow-up-review due window (Elder ch. 59 Trade Journal
# Section E) -- see get_closed_trades's `due_for_follow_up` parameter and this task's
# `decisions` entry for why 8-10 weeks (not a single exact date) was chosen.
_FOLLOW_UP_DUE_WINDOW_MIN = timedelta(weeks=8)
_FOLLOW_UP_DUE_WINDOW_MAX = timedelta(weeks=10)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _ordered_positions(db: Session) -> list[PositionORM]:
    """All held positions in a deterministic order (`entry_date`, then `id` as a tiebreaker
    for same-day entries), used by both GET /api/portfolio and GET /api/portfolio/risk so
    neither relies on incidental SQLite row-return order -- see this task's `decisions`
    entry."""
    return db.query(PositionORM).order_by(PositionORM.entry_date, PositionORM.id).all()


def _realized_losses_this_month_pct(db: Session, account: Account, as_of: date) -> float:
    """This calendar month's realized losses from `closed_trades`, as a percentage of current
    account equity -- the first half of the book's actual 6% Rule formula (docs/Analyse.md §7,
    per docs/ideas.md's ch. 51 cross-check: "the sum of your losses for the current month AND
    the risks in open trades"), which `app.portfolio.risk.total_open_risk_pct` alone never
    implemented on its own (it only ever summed the second half, current open-position risk)
    -- see the backend-trade-history-table task's `decisions` entry.

    Only losing trades (`realized_pnl < 0`) count towards the sum; a profitable month
    contributes 0, never a negative offset that would let this month's wins paper over a
    still-live 6%-rule breach. `as_of` anchors both the "this calendar month" window (`exit_date
    >= as_of`'s month start) and its upper bound (`exit_date <= as_of` -- a closed_trades row
    can't be dated in the future in practice, but this keeps the query's own contract explicit
    rather than relying on that never happening).

    Degrades to 0.0 (rather than raising) when `account.equity.total` isn't positive, mirroring
    `get_risk`'s existing `total_open_risk_pct` degrade-to-zero handling for the exact same
    precondition failure.
    """
    month_start = as_of.replace(day=1)
    rows = (
        db.query(ClosedTradeORM)
        .filter(ClosedTradeORM.exit_date >= month_start, ClosedTradeORM.exit_date <= as_of)
        .all()
    )
    realized_losses = sum(-row.realized_pnl for row in rows if row.realized_pnl < 0)
    try:
        return realized_losses_pct(account, realized_losses)
    except ValueError:
        return 0.0


def _compute_position_signal(e: EnrichedPosition, provider: DataProvider) -> SignalResult | None:
    """Runs the same fetch-then-`analyse()` pipeline `GET /api/stocks/{ticker}/analysis` and
    `GET /api/watchlist` use, for a single already-price-enriched position, returning `None`
    instead of raising if the signal can't be computed right now -- see the
    api-portfolio-position-signal task's `decisions` entry.

    Reuses `e.daily_ohlcv` (the same fetch `enrich_positions_with_price` already made to
    derive `current_price`) rather than fetching daily data a second time; a `None`
    `e.daily_ohlcv` means that fetch already failed, so the signal is unconditionally
    unavailable too (mirrors `app.api.routers.portfolio.get_risk`'s identical
    `e.position.current_price is None or e.daily_ohlcv is None` guard). Only the weekly
    history (needed for Screen 1/Tide, not fetched by `enrich_positions_with_price` at all)
    is fetched here, degrading to `None` on `DataProviderError` -- the same narrow
    (not bare `except Exception`) catch `app.api.routers.watchlist._compute_signal` uses, so a
    genuine bug in `analyse()` itself still surfaces as a loud 500 rather than a silently
    swallowed null field.

    `drop_malformed_daily_bars` is called here with its default `require_full_ohlc_on_latest_bar
    =True` -- NOT `get_risk`'s `False` -- because `analyse()` (unlike `evaluate_exit_flags`)
    genuinely reads the latest bar's own open/high/low, not just its close (Elder-Ray needs
    high/low, Wave/Trigger need the day's full range); handing it a bar with NaN open/high/low
    would feed garbage into those computations rather than degrade gracefully. But dropping the
    latest bar outright, on its own, isn't safe either: `e.daily_ohlcv` is only non-`None` here
    because `app.portfolio.pricing.latest_close` already found a *valid close* on that exact
    latest bar (its own check is close-only, permissive) and derived `e.position.current_price`
    from it -- so if that same latest bar fails this stricter filter, it must be because its
    open/high/low are NaN (the yfinance "not yet settled" shape `drop_malformed_daily_bars`'s
    own docstring documents), not because its close is missing. Silently proceeding with the
    filtered frame in that case would compute `signal`/`confidence`/`confidence_band` from
    *yesterday's* bar while `current_price`/`unrealized_pnl_pct` on the same position reflect
    *today's* close -- a one-day desync with no error and no null to flag it. Detecting that
    exact condition (the latest bar didn't survive filtering) and returning `None` instead
    keeps the two families of fields consistent: either both come from today's bar, or the
    signal ones are null until today's bar has a full OHLC -- never a silent mix of the two."""
    if e.daily_ohlcv is None:
        return None
    try:
        weekly_ohlcv = provider.get_weekly_ohlcv(e.position.ticker)
    except DataProviderError:
        return None

    daily_ohlcv = drop_malformed_daily_bars(e.daily_ohlcv)
    if daily_ohlcv.empty or daily_ohlcv.index[-1] != e.daily_ohlcv.index[-1]:
        return None
    return analyse(e.position.ticker, daily_ohlcv, weekly_ohlcv)


def _grade_closed_trades(
    rows: list[ClosedTradeORM], provider: DataProvider
) -> dict[str, TradeGrade]:
    """Grades every row in `rows` (`app.portfolio.grading.grade_trade_from_filtered_history`),
    fetching each distinct ticker's daily OHLCV at most once -- closed trades for the same
    ticker (a ticker bought, sold, and later bought/sold again) share one fetch rather than
    one per row. Returns a dict keyed by `ClosedTradeORM.id`.

    The two more expensive per-ticker derivations -- `drop_malformed_daily_bars` and the full
    `autoenvelope()` rolling-window computation over the whole history -- are likewise derived
    at most once per ticker (alongside the fetch itself) and shared across every row for that
    ticker, rather than being recomputed by `grade_closed_trade` once per row: a ticker with
    many round-trip closed trades (e.g. 50 AAPL buy/sell pairs) would otherwise trigger 50
    separate dropna passes and 50 separate autoenvelope() computations over the identical
    frame -- see the `backend-trade-grading-followups` task.

    A ticker whose fetch fails (`DataProviderError` -- unknown/delisted ticker, provider
    unavailable) grades every one of its rows as an all-`None` `TradeGrade` rather than
    raising or excluding the row from the response entirely -- same degrade-gracefully
    convention as `_compute_position_signal`/`enrich_positions_with_price`: a closed trade
    whose grade can't currently be computed is still a real trade the user closed, and should
    still show up in their trade history with its own recorded price/date/P&L fields intact,
    just without a grade attached."""
    filtered_frames: dict[str, pd.DataFrame | None] = {}
    channels: dict[str, pd.DataFrame] = {}
    grades: dict[str, TradeGrade] = {}
    for row in rows:
        if row.ticker not in filtered_frames:
            try:
                raw_frame = provider.get_daily_ohlcv(row.ticker)
            except DataProviderError:
                filtered_frames[row.ticker] = None
            else:
                filtered_frame = drop_malformed_daily_bars(raw_frame)
                filtered_frames[row.ticker] = filtered_frame
                channels[row.ticker] = autoenvelope(filtered_frame["close"])
        filtered_frame = filtered_frames[row.ticker]
        if filtered_frame is None:
            grades[row.id] = TradeGrade(
                buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None
            )
        else:
            grades[row.id] = grade_trade_from_filtered_history(
                entry_price=row.entry_price,
                entry_date=row.entry_date,
                exit_price=row.exit_price,
                exit_date=row.exit_date,
                filtered_daily_ohlcv=filtered_frame,
                channel=channels[row.ticker],
            )
    return grades


_EXIT_REASON_VALUES: frozenset[str] = frozenset(get_args(ExitReasonOut))

# Distinct out-of-taxonomy exit_reason values already warned about in this process's lifetime
# (backend-closed-trades-legacy-exit-reason-500-followups) -- see _normalize_exit_reason's
# docstring for why this is de-duplicated rather than logged on every request. No size cap:
# it grows by one entry per distinct out-of-taxonomy value ever seen, for the process's whole
# lifetime. Accepted as-is (not a defensive cap) because the write path enum-validates
# exit_reason (see `exit_reason: ExitReason = Query(...)` below), so only pre-existing
# legacy/hand-inserted rows can ever land here -- not something ordinary API usage or repeated
# requests can grow unboundedly. See backend-closed-trades-legacy-exit-reason-500-followups-followups.
_warned_exit_reason_values: set[str] = set()


def _normalize_exit_reason(raw_exit_reason: str) -> ExitReasonOut:
    """Coerces a `closed_trades` row's raw (unconstrained-`String`-column, see
    `app.db.models.ClosedTradeORM.exit_reason`) `exit_reason` value to a valid `ExitReasonOut`
    Literal, falling back to `'unspecified'` for anything outside the current 8-value taxonomy
    instead of letting `ClosedTradeOut(...)` raise a `pydantic.ValidationError` for the whole
    request -- see the backend-closed-trades-legacy-exit-reason-500 task's `decisions` entry
    for why a fallback was chosen over widening the taxonomy.

    Logs a `logger.warning` the first time a given out-of-taxonomy value is seen in this
    process, then stays silent for that same value on every subsequent request -- a
    long-lived legacy row (e.g. hand-inserted dev data) would otherwise produce an identical
    warning on every single `GET /api/portfolio/closed-trades` call indefinitely. See the
    backend-closed-trades-legacy-exit-reason-500-followups task's `decisions` entry."""
    if raw_exit_reason in _EXIT_REASON_VALUES:
        return cast(ExitReasonOut, raw_exit_reason)
    # Best-effort, not atomic: this check-then-act on a module-level set can race under
    # concurrent requests (get_closed_trades is a sync `def` route, run in FastAPI/Starlette's
    # thread-pool executor) and occasionally emit a duplicate warning for the same value --
    # an accepted, known tradeoff, not a regression. See
    # backend-closed-trades-legacy-exit-reason-500-followups-followups's decisions entry.
    if raw_exit_reason not in _warned_exit_reason_values:
        _warned_exit_reason_values.add(raw_exit_reason)
        logger.warning(
            "closed_trades row has out-of-taxonomy exit_reason %r -- reporting as "
            "'unspecified' (further occurrences of this same value are suppressed for the "
            "rest of this process's lifetime)",
            raw_exit_reason,
        )
    return "unspecified"


def _to_closed_trade_out(row: ClosedTradeORM, grade: TradeGrade) -> ClosedTradeOut:
    """Builds the `ClosedTradeOut` for one `closed_trades` row + its already-computed
    `TradeGrade` (from `_grade_closed_trades`). Shared by `get_closed_trades` and
    `record_follow_up_review` so the two routes' identical field-by-field mapping -- every
    field `ClosedTradeOut` has grown over time (grades, entry notes, strategy, the follow-up
    review fields) -- has exactly one place to update, instead of two call sites that must be
    kept in sync by hand -- see the backend-trade-journal-followup-review-followups task."""
    return ClosedTradeOut(
        id=row.id,
        ticker=row.ticker,
        quantity=row.quantity,
        entry_price=row.entry_price,
        entry_date=row.entry_date,
        exit_price=row.exit_price,
        exit_date=row.exit_date,
        realized_pnl=row.realized_pnl,
        exit_reason=_normalize_exit_reason(row.exit_reason),
        buy_grade_pct=grade.buy_grade_pct,
        sell_grade_pct=grade.sell_grade_pct,
        trade_grade_pct=grade.trade_grade_pct,
        trade_letter_grade=trade_letter_grade(grade.trade_grade_pct),
        entry_notes=row.entry_notes,
        strategy=row.strategy,
        follow_up_notes=row.follow_up_notes,
        follow_up_reviewed_at=row.follow_up_reviewed_at,
    )


# Route bodies are stubs (see the add-api-endpoint skill) — the signatures,
# response_models, and error responses below are real and drive the OpenAPI
# schema the frontend generates its types from (docs/architecture/API.md).
# Keep this contract accurate even while unimplemented: it's what lets
# frontend and backend work proceed in parallel.


@router.get(
    "",
    response_model=PortfolioResponse,
    operation_id="get_portfolio",
    summary="Get current positions and account equity",
)
def get_portfolio(
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> PortfolioResponse:
    """All held positions plus account equity (cash + mark-to-market positions value).
    `current_price`/`unrealized_pnl_pct` on each position are enriched from the market
    data cache and are null only if a price fetch for that ticker has failed. A position
    whose price couldn't be fetched contributes nothing to `equity.positions_value`
    (it can't be marked to market) rather than falling back to cost basis — see this
    task's `decisions` entry. The fetch-and-degrade-gracefully loop itself lives in
    `app.portfolio.pricing` (shared with GET /api/portfolio/risk) — see the
    api-portfolio-risk task's `decisions` entry.

    `signal`/`confidence`/`confidence_band` on each position come from the exact same
    Triple Screen signal engine (`app.signals.engine.analyse`, docs/Analyse.md §5) GET
    /api/stocks/{ticker}/analysis and GET /api/watchlist use -- no second, divergent signal
    computation. Null together on a position whose signal couldn't be computed right now
    (its price fetch already failed, the separate weekly-history fetch the signal engine
    needs failed, or the latest daily bar has a valid close but NaN open/high/low -- the
    signal fields go null rather than silently reflecting yesterday's bar while
    `current_price` reflects today's), mirroring `current_price`'s own null-on-failure
    convention and WatchlistItemOut's identical precedent -- the position itself is still
    returned, never dropped or 500'd, just as a price-fetch failure never drops it -- see
    `_compute_position_signal`'s docstring and the api-portfolio-position-signal task's
    `decisions` entry."""
    account = db.get(AccountORM, 1)
    cash = account.cash if account is not None else 0.0

    enriched = enrich_positions_with_price(_ordered_positions(db), provider)
    value = positions_value(enriched)

    positions_out: list[PositionOut] = []
    for e in enriched:
        signal_result = _compute_position_signal(e, provider)
        positions_out.append(
            PositionOut(
                id=e.position.id,
                ticker=e.position.ticker,
                quantity=e.position.quantity,
                avg_cost_basis=e.position.avg_cost_basis,
                entry_date=e.position.entry_date,
                current_price=e.position.current_price,
                unrealized_pnl_pct=e.position.unrealized_pnl_pct,
                signal=signal_result.signal if signal_result is not None else None,
                confidence=signal_result.confidence if signal_result is not None else None,
                confidence_band=signal_result.confidence_band
                if signal_result is not None
                else None,
                entry_notes=e.entry_notes,
                strategy=e.strategy,
            )
        )

    return PortfolioResponse(
        equity=Equity(cash=cash, positions_value=value, total=cash + value),
        positions=positions_out,
    )


@router.post(
    "/positions",
    response_model=PositionOut,
    status_code=201,
    operation_id="add_position",
    summary="Add or update a position",
    responses={
        422: {
            "description": "Either of two distinct shapes, both under HTTP 422: ordinary "
            "request-body validation failure (FastAPI's standard HTTPValidationError — "
            "`detail` is a list of per-field errors), or merging with an existing position "
            "would produce a quantity/avg_cost_basis too large to represent (`detail` is a "
            "single string, ErrorDetail).",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                            {"$ref": "#/components/schemas/ErrorDetail"},
                        ],
                    },
                },
            },
        },
    },
)
def add_position(position: PositionIn, db: Session = Depends(get_db)) -> PositionOut:
    """Creates a position from manual entry / CSV-import data. If a position for this ticker
    already exists it is merged rather than duplicated: quantities are summed and
    avg_cost_basis becomes the quantity-weighted average of the existing and incoming cost
    bases (mirrors how a brokerage averages up/down a position instead of tracking separate
    lots) — see the api-portfolio-add-position task's `decisions` for the full rationale and
    the rejected reject-with-409 alternative. entry_date keeps the earlier of the two dates.
    `entry_notes` (Elder ch. 59 Trade Journal Section A) is set outright on a new position; on
    a merge, an incoming note is appended to the existing one (blank-line separated) rather
    than overwritten, so notes from multiple buys aren't lost -- see the
    backend-trade-journal-entry-notes task's `decisions`.
    `strategy` (Elder ch. 55/56/58/59's personal named strategy tag) is set outright on a new
    position; on a merge, an incoming `strategy` *overwrites* the existing one (unlike
    `entry_notes`) so this field stays a single clean tag for future strategy-segmented
    grouping/equity-curve use, rather than accumulating multiple concatenated values -- a
    merge with no incoming `strategy` leaves the existing one untouched -- see the
    backend-trade-strategy-tagging task's `decisions`. Like `entry_notes`, `strategy` is
    stripped of leading/trailing whitespace and a blank/whitespace-only value normalizes to
    null at the schema layer; neither field is case-folded on write, so casing is preserved
    exactly as typed for both -- the real asymmetry between the two is the merge behavior
    above (`strategy` overwrites, `entry_notes` appends), not casing -- see the
    backend-trade-strategy-tagging-followups task's `decisions`.
    `current_price`/`unrealized_pnl_pct` are always null here: price enrichment happens on
    read (GET /api/portfolio), not on write, and isn't available until the data-cache task
    lands. `signal`/`confidence`/`confidence_band` are always null here too, for the same
    reason -- signal annotation happens on read (GET /api/portfolio), not on write, mirroring
    POST /api/watchlist's identical null-on-write convention for the same fields."""
    ticker = position.ticker.upper()
    existing = db.query(PositionORM).filter(PositionORM.ticker == ticker).one_or_none()

    if existing is None:
        row = PositionORM(
            id=f"pos_{uuid.uuid4().hex[:12]}",
            ticker=ticker,
            quantity=position.quantity,
            avg_cost_basis=position.avg_cost_basis,
            entry_date=position.entry_date,
            entry_notes=position.entry_notes,
            strategy=position.strategy,
        )
        db.add(row)
    else:
        # Merge arithmetic runs on decimal.Decimal rather than the native floats directly:
        # two individually-valid, individually-finite floats (each already rejected if
        # non-finite/non-positive at the schema layer) can still overflow Python float64
        # arithmetic to inf, and an inf/inf weighted-average division silently produces nan
        # rather than raising -- see this task's `decisions` for the full round-3 history.
        # Decimal's default context has far more exponent headroom than float64, so the sum
        # and weighted-average division themselves don't silently overflow; the remaining
        # risk is the final float64 conversion for storage (the ORM columns are SQLAlchemy
        # Float), which *also* silently saturates to inf rather than raising -- so the
        # explicit math.isfinite() check below, not Decimal alone, is what turns that case
        # into a clean 422 instead of an unhandled 500 from db.commit(). (existing.quantity/
        # avg_cost_basis and position.quantity/avg_cost_basis are always finite floats by the
        # time execution reaches here -- either already-committed rows or schema-validated
        # `allow_inf_nan=False`/`gt=0` request fields -- so Decimal construction and division
        # below can't themselves raise; there's deliberately no try/except DecimalException
        # around them.)
        existing_quantity_dec = Decimal(existing.quantity)
        incoming_quantity_dec = Decimal(position.quantity)
        merged_quantity_dec = existing_quantity_dec + incoming_quantity_dec
        merged_avg_cost_basis_dec = (
            existing_quantity_dec * Decimal(existing.avg_cost_basis)
            + incoming_quantity_dec * Decimal(position.avg_cost_basis)
        ) / merged_quantity_dec
        merged_quantity = float(merged_quantity_dec)
        merged_avg_cost_basis = float(merged_avg_cost_basis_dec)

        if not (math.isfinite(merged_quantity) and math.isfinite(merged_avg_cost_basis)):
            raise HTTPException(
                status_code=422,
                detail="Merging this position with the existing one would produce a quantity "
                "or average cost basis too large to represent (overflow). Reduce the "
                "quantity/avg_cost_basis or split the addition into smaller increments.",
            )

        existing.quantity = merged_quantity
        existing.avg_cost_basis = merged_avg_cost_basis
        existing.entry_date = min(existing.entry_date, position.entry_date)
        # entry_notes merges by appending rather than overwriting -- see this task's
        # `decisions` entry: an incoming note is never silently dropped just because a
        # position already existed, and a merge with no incoming note leaves the existing
        # one untouched (there's nothing to append). PositionIn's own field_validator already
        # strips whitespace and normalizes a blank/whitespace-only note to None before this
        # handler ever runs, so a whitespace-only incoming note is falsy here too -- see the
        # backend-trade-journal-entry-notes-followups task's `decisions`.
        if position.entry_notes:
            existing.entry_notes = (
                f"{existing.entry_notes}\n\n{position.entry_notes}"
                if existing.entry_notes
                else position.entry_notes
            )
        # strategy merges by overwriting rather than appending -- see the
        # backend-trade-strategy-tagging task's `decisions` entry: unlike entry_notes'
        # narrative text, strategy is meant to be grouped/aggregated on exactly
        # (equity-curves-by-strategy, the future backend-trade-apgar task), so a merge with an
        # incoming strategy replaces the existing tag outright. A merge with no incoming
        # strategy leaves the existing one untouched (nothing to replace it with).
        # PositionIn's own field_validator already strips whitespace and normalizes a blank/
        # whitespace-only tag to None before this handler ever runs, so a whitespace-only
        # incoming tag is falsy here too and never overwrites an existing tag with whitespace
        # -- see the backend-trade-strategy-tagging-followups task's `decisions`.
        if position.strategy:
            existing.strategy = position.strategy
        row = existing

    db.commit()
    db.refresh(row)

    return PositionOut(
        id=row.id,
        ticker=row.ticker,
        quantity=row.quantity,
        avg_cost_basis=row.avg_cost_basis,
        entry_date=row.entry_date,
        current_price=None,
        unrealized_pnl_pct=None,
        signal=None,
        confidence=None,
        confidence_band=None,
        entry_notes=row.entry_notes,
        strategy=row.strategy,
    )


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    operation_id="delete_position",
    summary="Remove a position, recording it as a closed trade",
    responses={
        404: {"model": ErrorDetail, "description": "Position not found"},
        422: {
            "description": "Either of two distinct shapes, both under HTTP 422: ordinary "
            "query-param validation failure (FastAPI's standard HTTPValidationError -- "
            "`detail` is a list of per-field errors, e.g. a non-positive `exit_price` or an "
            "invalid `exit_reason`), or the manual-override validation this endpoint does "
            "itself once both a position and an `exit_price`/`exit_date` pair are known "
            "(`detail` is a single string, ErrorDetail): only one of `exit_price`/`exit_date` "
            "supplied instead of both, or an `exit_date` before the position's `entry_date`.",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                            {"$ref": "#/components/schemas/ErrorDetail"},
                        ],
                    },
                },
            },
        },
    },
)
def delete_position(
    position_id: str,
    exit_reason: ExitReason = Query(
        default=ExitReason.UNSPECIFIED,
        description="Why this position is being closed, from Elder's own taxonomy "
        "(docs/Analyse.md §7 / docs/ideas.md's ch. 51 cross-check). Defaults to 'unspecified' "
        "-- not one of Elder's own tags -- when the caller doesn't supply one, since this "
        "endpoint has no other way to know why the user is closing the position.",
    ),
    exit_price: float | None = Query(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Optional manual override for the exit price recorded on the resulting "
        "`closed_trades` row, for backfilling a trade that already happened in the past "
        "(importing real trading history, or logging a sale a few days late with its actual "
        "fill price) -- see the backend-close-position-manual-exit task's `decisions` entry "
        "for why this revisits backend-trade-history-table's original market-price-only "
        "design. Must be supplied together with `exit_date` (both or neither); omitting both "
        "keeps the original default of pricing at today's live market close. Must be a "
        "positive, finite number (Infinity/NaN are rejected).",
    ),
    exit_date: date | None = Query(
        default=None,
        description="Optional manual override for the exit date recorded on the resulting "
        "`closed_trades` row, paired with `exit_price` (see its description). Must not be "
        "before the position's own `entry_date` -- a trade can't be closed before it was "
        "opened.",
    ),
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> None:
    """Removes a position entirely. There is no partial-quantity reduction endpoint --
    reducing a position means deleting and re-adding it with the new quantity.

    Also records a `closed_trades` row (ticker, quantity, entry price/date, exit price/date,
    realized P&L, exit_reason, entry_notes, strategy) -- the trade-history/ledger this app
    previously had no model for at all -- feeding both GET /api/portfolio/risk's
    realized-losses-this-month component of the 6% Rule (docs/Analyse.md §7) and, longer-term,
    the backend-trade-grading task's buy/sell/trade-grade formulas plus a trade-journal
    frontend page. `entry_notes` is carried over verbatim from the position's own entry note
    (Elder ch. 59 Trade Journal Section A, see POST /api/portfolio/positions) -- null if none
    was ever recorded. `strategy` (Elder ch. 55/56/58/59's personal named strategy tag) is
    carried over the same way -- null if none was ever recorded.

    By default, `exit_price` is today's latest close for this ticker, fetched the same way
    `current_price` is everywhere else in this router (`app.portfolio.pricing.latest_close`),
    and `exit_date` is today -- not a caller-supplied price/date, since this app already treats
    "current market price" as authoritative for mark-to-market elsewhere rather than trusting a
    client-supplied number. Callers may instead supply `exit_price` and `exit_date` together to
    backfill a trade that already happened in the past (see their own descriptions above and
    the backend-close-position-manual-exit task's `decisions` entry for why this is a
    deliberate, narrow exception to that rule rather than a silent override of it).
    `realized_pnl` is `quantity * (exit_price - avg_cost_basis)` either way. If the default
    (no override) price fetch fails (unknown/delisted ticker, provider unavailable), the
    position is still deleted -- a data-provider outage must never block removing a position --
    but no `closed_trades` row is recorded, since there's no way to compute a realized P&L
    without an exit price; see the backend-trade-history-table task's `decisions` entry for the
    full rationale."""
    row = db.get(PositionORM, position_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Position '{position_id}' not found")

    if (exit_price is None) != (exit_date is None):
        raise HTTPException(
            status_code=422,
            detail="exit_price and exit_date must be supplied together, or neither -- got "
            f"exit_price={exit_price!r}, exit_date={exit_date!r}",
        )

    resolved_exit_price: float | None
    resolved_exit_date: date
    if exit_price is not None and exit_date is not None:
        if exit_date < row.entry_date:
            raise HTTPException(
                status_code=422,
                detail=f"exit_date ({exit_date}) must not be before this position's "
                f"entry_date ({row.entry_date})",
            )
        resolved_exit_price = exit_price
        resolved_exit_date = exit_date
    else:
        resolved_exit_price, _ = latest_close(provider, row.ticker)
        resolved_exit_date = today()

    if resolved_exit_price is not None:
        db.add(
            ClosedTradeORM(
                id=f"trade_{uuid.uuid4().hex[:12]}",
                ticker=row.ticker,
                quantity=row.quantity,
                entry_price=row.avg_cost_basis,
                entry_date=row.entry_date,
                exit_price=resolved_exit_price,
                exit_date=resolved_exit_date,
                realized_pnl=row.quantity * (resolved_exit_price - row.avg_cost_basis),
                exit_reason=exit_reason.value,
                entry_notes=row.entry_notes,
                strategy=row.strategy,
            )
        )

    db.delete(row)
    db.commit()


def _profit_target_to_schema(target: ProfitTarget) -> ProfitTargetOut:
    """Maps `app.portfolio.profit_target.ProfitTarget` (the domain type) onto `ProfitTargetOut`
    (the API schema) -- identical straight 1:1 field copy to `app.api.routers.stocks
    ._profit_target_to_schema` (no `pd.Timestamp` fields, so nothing to convert). Duplicated
    here rather than imported across routers: this codebase has no existing precedent for one
    router importing another's private per-router mapping helper (every `_..._to_schema`
    function here and in `stocks.py` is private to its own module), and `ProfitTargetOut`'s five
    fields are an already-reviewed, stable shape -- see the backend-profit-target-open-position
    task's `decisions` entry."""
    return ProfitTargetOut(
        price=target.price,
        source=target.source,
        distance_to_stop=target.distance_to_stop,
        distance_to_target=target.distance_to_target,
        reward_risk_ratio=target.reward_risk_ratio,
        meets_minimum_reward_risk=target.meets_minimum_reward_risk,
    )


@router.get(
    "/risk",
    response_model=RiskResponse,
    operation_id="get_portfolio_risk",
    summary="Get the 2%/6% rule evaluation and per-position exit flags",
)
def get_risk(
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> RiskResponse:
    """Per-position protective stop, 2%-rule risk, and exit flags, plus the portfolio-wide
    6%-rule total (docs/Analyse.md §7). `exit_flags` can be non-empty even when the
    corresponding stock's fresh technical signal is HOLD — risk-driven exits are
    independent of entry-signal logic by design.

    `total_open_risk_pct` is the book's actual two-part 6% Rule total (docs/Analyse.md §7, per
    docs/ideas.md's ch. 51 cross-check): this calendar month's realized losses
    (`realized_losses_this_month_pct`, from the `closed_trades` table `DELETE
    /api/portfolio/positions/{id}` populates) plus current open-position risk (`app.portfolio
    .risk.total_open_risk_pct`, summed over positions with a known stop) -- see the
    backend-trade-history-table task's `decisions` entry for why the field keeps this name
    despite now covering both halves.

    A position is silently excluded from `positions` (and so from the open-risk half of
    `total_open_risk_pct` -- see `app.portfolio.risk.total_open_risk_pct`) whenever its risk
    can't be computed at all: its current price
    couldn't be fetched (same degrade-gracefully rule as GET /api/portfolio — see this
    task's `decisions` entry), its daily history has fewer than 2 rows once any malformed
    bar is dropped (the minimum `evaluate_exit_flags` needs to test today's close against
    yesterday's stop), its weekly history couldn't be fetched, or
    `protective_stop`/`evaluate_exit_flags` raised for a malformed frame. `RiskPosition`'s
    fields are all non-nullable, so a position that can't be fully evaluated has no partial
    representation in this schema — see this task's `decisions` entry.

    `e.daily_ohlcv` is passed through `app.signals.engine.drop_malformed_daily_bars` before
    `protective_stop`/`evaluate_exit_flags` ever see it — mirroring GET
    /api/stocks/{ticker}/analysis's identical filtering — so a malformed bar anywhere in a
    position's history can't silently suppress an exit flag via a NaN comparison quietly
    evaluating False. Called here with `require_full_ohlc_on_latest_bar=False`, unlike GET
    /api/stocks/{ticker}/analysis's default-`True` call: the *latest* bar is dropped only if
    its own `close` is NaN, matching `app.portfolio.pricing.latest_close`'s own close-only
    validity rule for that exact bar (which is what `position.current_price` was derived
    from), rather than also requiring open/high/low there — a shape `latest_close` doesn't
    guard against, and one this pipeline's own downstream reads (`evaluate_exit_flags` and
    everything it calls) never touch for the latest bar anyway. Using the stricter default here
    would silently drop a real latest bar whose close is valid but whose open/high/low haven't
    settled yet, desyncing `position.current_price` from `daily_ohlcv`'s last row and making
    `evaluate_exit_flags` test yesterday's close against today's stop instead of today's — see
    the api-stocks-analysis-nullable-indicators-followups task's `decisions` entry for the full
    reasoning and the regression this reconciles.

    `profit_target` (`app.portfolio.profit_target.suggest_profit_target`, docs/Analyse.md §7)
    is computed for every position that reaches the per-position loop below, from that same
    filtered `daily_ohlcv`/its already-fetched `weekly_ohlcv` and a fresh support/resistance
    pass (`app.signals.support_resistance.detect_support_resistance_zones`) over that same
    `daily_ohlcv`, with this same position's already-computed `stop` (the identical
    `daily_ohlcv.iloc[:-1]`-derived value `protective_stop` below reports) passed straight
    through into its reward:risk math -- so `profit_target`'s own notion of the stop can never
    silently disagree with `RiskPosition.protective_stop` within the same response (previously
    `suggest_profit_target` recomputed its own, different stop from the full frame; see this
    task's `decisions` entry) -- UNLIKE `AnalysisResponse.profit_target` on GET /api/stocks/{ticker}
    /analysis, this is never gated on that ticker's current live signal being BUY: this is an
    already-open long position with a real entry, and ch. 53 read directly doesn't gate an
    open position's target to entry-day/fresh-BUY-signal only ("a target set at entry ... is
    meant to be tracked for the life of the trade") -- see the
    backend-profit-target-open-position task's `decisions` entry, which revisits
    `backend-profit-target`'s original BUY-only decision for this exact open-position case.
    `profit_target` is independently nullable within a `RiskPosition` entry (unlike every
    other field on this schema, which are all non-nullable and instead gate whether the whole
    position appears in `positions` at all) -- a `ValueError` computing it (or neither target
    technique producing a candidate) degrades to `profit_target=None` for that one position
    rather than excluding it from `positions` entirely, since a missing profit target is far
    less consequential than a missing stop/risk-pct/exit-flags.

    Known, accepted perf trade-off (not fixed here -- see the
    backend-profit-target-open-position-followups task's `decisions` entry): both
    `detect_support_resistance_zones` (a whole-history swing-point/clustering pass) and
    `suggest_profit_target`'s own weekly-Autoenvelope + swing-low work run fresh, uncached, for
    every position on every call to this endpoint, unlike `stops`/`daily_by_id`/`weekly_by_id`
    above, which this same loop deliberately computes once and reuses. Cheap enough at today's
    position counts/polling frequency to leave as plain per-request computation rather than
    adding a new cache table (with its own TTL/invalidation policy, migration, and tests) for a
    problem that's speculative today -- revisit if this endpoint's poll frequency or position
    count grows enough to make it a real cost, following `app.data.cache.CachedDataProvider`'s
    existing (ticker, interval)-keyed pattern for the shape such a cache would take."""
    account_row = db.get(AccountORM, 1)
    cash = account_row.cash if account_row is not None else 0.0

    enriched = enrich_positions_with_price(_ordered_positions(db), provider)
    value = positions_value(enriched)
    account = Account(
        equity=DomainEquity(cash=cash, positions_value=value, total=cash + value),
        positions=[e.position for e in enriched],
    )

    # First pass: figure out which positions have enough data to compute a protective stop
    # at all, and fetch each one's weekly history (needed for the tide_flipped_bearish exit
    # flag) up front so the second pass can call evaluate_exit_flags without any further
    # fetches. protective_stop() is attempted before the weekly fetch -- it's a pure
    # computation over the frame we already have in hand, so a position excluded on the
    # daily side (missing column, too short) never pays for a weekly network/cache round
    # trip that would just get thrown away.
    #
    # e.daily_ohlcv is filtered through drop_malformed_daily_bars up front, before the
    # length check and every downstream use (protective_stop here, evaluate_exit_flags in
    # the second pass below) -- see this handler's own docstring and the
    # api-stocks-analysis-nullable-indicators-followups task's `decisions` entry. The
    # filtered frame is cached per position (daily_by_id) alongside stops/weekly_by_id so
    # the second pass reuses it rather than re-filtering.
    stops: dict[str, float] = {}
    weekly_by_id: dict[str, pd.DataFrame] = {}
    daily_by_id: dict[str, pd.DataFrame] = {}
    for e in enriched:
        if e.position.current_price is None or e.daily_ohlcv is None:
            continue
        daily_ohlcv = drop_malformed_daily_bars(
            e.daily_ohlcv, require_full_ohlc_on_latest_bar=False
        )
        if len(daily_ohlcv) < 2:
            continue
        try:
            stop = protective_stop(e.position, daily_ohlcv.iloc[:-1])
        except ValueError:
            continue
        try:
            weekly_ohlcv = provider.get_weekly_ohlcv(e.position.ticker)
        except DataProviderError:
            continue
        stops[e.position.id] = stop
        weekly_by_id[e.position.id] = weekly_ohlcv
        daily_by_id[e.position.id] = daily_ohlcv

    # account.equity.total <= 0 (e.g. cash deep enough negative to outweigh positions_value)
    # makes position_risk_pct -- called internally by total_open_risk_pct for every position
    # in `stops` -- raise ValueError, the same precondition failure the per-position loop
    # below already guards against for each position individually. Guard this call the same
    # way: an unknown open-position risk degrades to 0.0 (and so never breaches the 6% rule on
    # its own) rather than propagating as an unhandled 500, consistent with every other
    # can't-be-computed case this endpoint documents as a silent exclusion.
    try:
        open_risk = total_open_risk_pct(account, stops)
    except ValueError:
        open_risk = 0.0
    # _realized_losses_this_month_pct degrades to 0.0 itself on the same account.equity.total
    # <= 0 precondition failure (see its own docstring), so no try/except is needed here.
    realized_losses_this_month = _realized_losses_this_month_pct(db, account, today())
    total_risk = open_risk + realized_losses_this_month
    six_percent_rule_breached = total_risk > _SIX_PERCENT_RULE_THRESHOLD

    risk_positions: list[RiskPosition] = []
    for e in enriched:
        if e.position.id not in stops:
            continue
        stop = stops[e.position.id]
        try:
            risk_pct = position_risk_pct(e.position, stop, account)
            exit_flags = evaluate_exit_flags(
                e.position,
                account,
                daily_by_id[e.position.id],
                weekly_by_id[e.position.id],
                total_risk,
            )
        except ValueError:
            continue

        # profit_target degrades to None on its own -- independently of the try/except above,
        # which governs whether this POSITION appears in `positions` at all. Computed
        # regardless of this ticker's current live signal (unlike AnalysisResponse.
        # profit_target's BUY-only gate) -- see this handler's own docstring and the
        # backend-profit-target-open-position task's `decisions` entry. `stop=stop` passes this
        # same position's already-computed `daily_ohlcv.iloc[:-1]`-derived protective stop
        # (identical to `RiskPosition.protective_stop` above) into suggest_profit_target's
        # reward:risk math, instead of letting it recompute a DIFFERENT stop from the full
        # daily_by_id[id] frame (today's bar included) -- see app.portfolio.profit_target's
        # module docstring and this task's `decisions` entry for why the two must never
        # silently disagree.
        profit_target = None
        try:
            domain_target = suggest_profit_target(
                daily_by_id[e.position.id],
                detect_support_resistance_zones(daily_by_id[e.position.id]),
                weekly_ohlcv=weekly_by_id[e.position.id],
                stop=stop,
            )
            if domain_target is not None:
                profit_target = _profit_target_to_schema(domain_target)
        except ValueError:
            profit_target = None

        risk_positions.append(
            RiskPosition(
                id=e.position.id,
                ticker=e.position.ticker,
                protective_stop=stop,
                position_risk_pct=risk_pct,
                two_percent_rule_breached=risk_pct > _TWO_PERCENT_RULE_THRESHOLD,
                exit_flags=exit_flags,
                profit_target=profit_target,
            )
        )

    return RiskResponse(
        total_open_risk_pct=total_risk,
        realized_losses_this_month_pct=realized_losses_this_month,
        six_percent_rule_breached=six_percent_rule_breached,
        positions=risk_positions,
    )


@router.get(
    "/closed-trades",
    response_model=ClosedTradesResponse,
    operation_id="get_closed_trades",
    summary="Get closed trades (trade history) with A-trade grades",
)
def get_closed_trades(
    due_for_follow_up: bool = Query(
        False,
        description="If true, only return closed trades due for their mandatory "
        "two-months-later follow-up review (Elder ch. 59 Trade Journal Section E, "
        "docs/ideas.md's ch. 59 entry): `follow_up_reviewed_at` is still null and `exit_date` "
        "falls between 8 and 10 weeks ago inclusive -- see the "
        "backend-trade-journal-followup-review task's `decisions` entry for why this specific "
        "8-10-week window (not a single exact date) was chosen. A trade exited less than 8 "
        "weeks ago isn't due yet; one exited more than 10 weeks ago without a review has "
        "aged out of this filtered view but still appears in the default, unfiltered listing. "
        "Defaults to false (every closed trade, the original behavior).",
    ),
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> ClosedTradesResponse:
    """Every row in the `closed_trades` table (docs/Analyse.md §7's trade-history/ledger
    table, populated by `DELETE /api/portfolio/positions/{id}`), most recently exited first
    (`exit_date` descending, `id` descending as a same-day tiebreaker -- mirrors
    `_ordered_positions`'s own deterministic-ordering rationale, just newest-first here since
    trade history is read for recency rather than portfolio composition). `due_for_follow_up`
    narrows this to trades due for Elder's mandatory two-months-later follow-up review -- see
    that parameter's own description for the exact window.

    Each trade is annotated with its `buy_grade_pct`/`sell_grade_pct`/`trade_grade_pct`
    (Elder ch. 55 "Is This an A-Trade?", docs/Analyse.md §7 / docs/ideas.md ch. 55) --
    `app.portfolio.grading.grade_trade_from_filtered_history`, sourced from the ticker's daily OHLCV (that
    day's own high/low) and the entry day's Autoenvelope/channel bounds (the same computation
    `AnalysisResponse.indicators.channel_upper`/`channel_lower` expose). Grading a trade is
    preferred over judging it by raw P&L alone, since it accounts for how much was
    realistically available to capture that day/that channel, not just what was captured.
    `trade_grade_pct` is additionally mapped to an Elder-style `trade_letter_grade` (A/B/C/D --
    see `app.portfolio.grading.trade_letter_grade`'s own docstring for the thresholds and the
    decision record behind them); `buy_grade_pct`/`sell_grade_pct` stay percentage-only since
    the book gives them no letter-grade scale at all.

    Grading never fails the request: a ticker whose current daily-history fetch fails, or a
    trade whose entry/exit date isn't an exact row in that history (e.g. it predates the
    fetched history, or falls inside the Autoenvelope's ~100-bar warm-up window), simply gets
    null grade fields on an otherwise fully-populated row -- see `_grade_closed_trades`'s
    docstring."""
    query = db.query(ClosedTradeORM)
    if due_for_follow_up:
        as_of = today()
        query = query.filter(
            ClosedTradeORM.follow_up_reviewed_at.is_(None),
            ClosedTradeORM.exit_date >= as_of - _FOLLOW_UP_DUE_WINDOW_MAX,
            ClosedTradeORM.exit_date <= as_of - _FOLLOW_UP_DUE_WINDOW_MIN,
        )
    rows = query.order_by(ClosedTradeORM.exit_date.desc(), ClosedTradeORM.id.desc()).all()
    grades = _grade_closed_trades(rows, provider)

    items: list[ClosedTradeOut] = []
    dropped_row_ids: list[str] = []
    for row in rows:
        try:
            items.append(_to_closed_trade_out(row, grades[row.id]))
        except Exception:
            # Defense in depth beyond the exit_reason-specific fallback above (which already
            # covers the one failure mode actually observed): a single malformed row -- of any
            # future/unanticipated kind, not just exit_reason -- is dropped and logged rather
            # than 500ing every other trade in the list. See the
            # backend-closed-trades-legacy-exit-reason-500 task's `decisions` entry.
            logger.exception("Skipping closed_trades row %s: failed to build API response", row.id)
            dropped_row_ids.append(row.id)
    if dropped_row_ids:
        # Aggregate signal on top of the per-row logger.exception above (backend-closed-trades-
        # legacy-exit-reason-500-followups' `decisions` entry): a handful of per-row tracebacks
        # scattered through the log is easy to miss, and by itself can't distinguish "one bad
        # legacy row" from a systemic bug affecting most/all of `rows` -- an on-call engineer
        # watching only aggregate log volume/error-rate metrics (not tailing every traceback)
        # needs a single line carrying the count and ratio to notice the latter. logger.error,
        # not .warning, since every row here already failed unexpectedly (dropped_row_ids is
        # only ever non-empty via the `except Exception` above, never the exit_reason fallback,
        # which never drops a row).
        logger.error(
            "GET /api/portfolio/closed-trades dropped %d/%d row(s) (%.1f%%) due to unexpected "
            "per-row failures: %s",
            len(dropped_row_ids),
            len(rows),
            100.0 * len(dropped_row_ids) / len(rows),
            dropped_row_ids,
        )
    return ClosedTradesResponse(items=items)


@router.post(
    "/closed-trades/{trade_id}/follow-up-review",
    response_model=ClosedTradeOut,
    operation_id="record_follow_up_review",
    summary="Record a two-months-later follow-up review for a closed trade",
    responses={
        404: {"model": ErrorDetail, "description": "Closed trade not found"},
    },
)
def record_follow_up_review(
    trade_id: str,
    review: FollowUpReviewIn,
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> ClosedTradeOut:
    """Records Elder's mandatory two-months-later follow-up review (ch. 59 Trade Journal
    Section E, docs/ideas.md's ch. 59 entry) for one `closed_trades` row: sets
    `follow_up_notes` to the supplied note and `follow_up_reviewed_at` to now (naive UTC, see
    `app.time_utils.utcnow`). Calling this again for the same `trade_id` overwrites both
    fields with the new call's values rather than appending or rejecting the second call --
    see this task's `decisions` entry for why (a personal journal tool, not an
    immutable/append-only audit log).

    Not restricted to trades currently `GET /api/portfolio/closed-trades?due_for_follow_up=true`
    would surface -- a trade can be reviewed early, late, or reviewed again, and this endpoint
    places no window restriction of its own on `trade_id`, only on whether it exists at all.

    Returns the full updated `ClosedTradeOut`, including a freshly recomputed grade (same
    `_grade_closed_trades` computation `GET /api/portfolio/closed-trades` uses), so a caller
    gets the complete, current record in one round trip rather than a bare acknowledgement."""
    row = db.get(ClosedTradeORM, trade_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Closed trade '{trade_id}' not found")

    row.follow_up_notes = review.follow_up_notes
    row.follow_up_reviewed_at = utcnow()
    db.commit()
    db.refresh(row)

    grades = _grade_closed_trades([row], provider)
    return _to_closed_trade_out(row, grades[row.id])


@router.post(
    "/trade-apgar",
    response_model=TradeApgarOut,
    operation_id="score_trade_apgar",
    summary="Score a pre-trade 'Trade Apgar' go/no-go check for a ticker",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        422: {
            "model": ErrorDetail,
            "description": "Either the ticker's fetched weekly history has fewer than 26 "
            "weeks (the same minimum GET /api/stocks/{ticker}/analysis's weekly fetch "
            "enforces), or its fetched daily history is empty once any malformed bar is "
            "dropped -- either way, there isn't enough data to auto-populate this ticker's "
            "weekly-Impulse/daily-Impulse/price-vs-value questions.",
        },
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def evaluate_trade_apgar(
    request: TradeApgarIn, provider: DataProvider = Depends(get_data_provider)
) -> TradeApgarOut:
    """Elder ch. 58's "Trade Apgar" (docs/Analyse.md §7 / docs/ideas.md ch. 58): a fixed
    5-question, 0/1/2-each pre-trade go/no-go score matching Elder's own example strategy --
    the pre-trade counterpart to ch. 55's after-the-fact `GET /api/portfolio/closed-trades`
    grading. `go` is true only when the summed score is >= 7 *and* no single question scored
    0 -- see `app.portfolio.trade_apgar.score_trade_apgar`'s own docstring.

    Three of the five questions are auto-populated (`source: "auto"` on the returned
    `TradeApgarQuestionOut`) from the exact same `app.signals.engine.analyse()` pipeline
    every other signal-facing endpoint uses for `request.ticker` -- `weekly_impulse` and
    `daily_impulse` are the weekly/daily Impulse System colors (docs/Analyse.md §3;
    `weekly_impulse` is `app.signals.impulse.evaluate_impulse` run directly on the fetched
    weekly OHLCV, the identical computation `evaluate_tide` uses internally to decide Screen
    1, since `analyse()` itself only exposes that color already mapped onto Screen 1's own
    BULLISH/BEARISH/NEUTRAL vocabulary -- see this task's `decisions` entry), and
    `price_vs_value` classifies today's close against ch. 41's EMA(13)/EMA(26) "value zone"
    (`app.portfolio.trade_apgar.price_vs_value_zone`) -- *not* the Autoenvelope/channel band
    `AnalysisResponse.indicators.channel_upper`/`channel_lower` expose, a distinct indicator
    despite both being drawn on the same price chart (see this task's `decisions` entry for
    the correction and `price_vs_value_zone`'s own docstring). `false_breakout_status` and
    `perfection` are always `request`'s own manual inputs, echoed back verbatim -- this first
    version derives no suggested starting value for either from
    `app.signals.kangaroo_tail`/`app.signals.support_resistance`, even though both are
    closely related detections -- see this task's `decisions` entry for why."""
    ticker = request.ticker.upper()
    try:
        daily_ohlcv = provider.get_daily_ohlcv(ticker)
        weekly_ohlcv = provider.get_weekly_ohlcv(ticker)
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)
    if daily_ohlcv.empty:
        raise HTTPException(
            status_code=422,
            detail=f"'{ticker}' has no usable daily history (empty once any malformed bar is "
            "dropped) to compute its Trade Apgar's auto-populated questions from.",
        )

    result = analyse(ticker, daily_ohlcv, weekly_ohlcv)
    weekly_impulse = cast(ImpulseColor, evaluate_impulse(weekly_ohlcv))
    daily_close = float(daily_ohlcv["close"].iloc[-1])
    price_vs_value = price_vs_value_zone(
        daily_close, result.indicators["ema_13"], result.indicators["ema_26"]
    )

    apgar = score_trade_apgar(
        weekly_impulse=weekly_impulse,
        daily_impulse=cast(ImpulseColor, result.screens["impulse"]),
        price_vs_value=price_vs_value,
        false_breakout_status=request.false_breakout_status,
        perfection=request.perfection,
    )

    return TradeApgarOut(
        ticker=ticker,
        questions=[
            TradeApgarQuestionOut(
                key=q.key, label=q.label, value=q.value, score=q.score, source=q.source
            )
            for q in apgar.questions
        ],
        total_score=apgar.total_score,
        go=apgar.go,
    )
