import math
import uuid
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.api.schemas import (
    Equity,
    ErrorDetail,
    PortfolioResponse,
    PositionIn,
    PositionOut,
    RiskPosition,
    RiskResponse,
)
from app.data.base import DataProvider
from app.data.exceptions import DataProviderError
from app.db.models import AccountORM, PositionORM
from app.db.session import get_db
from app.portfolio.exits import evaluate_exit_flags
from app.portfolio.models import Account
from app.portfolio.models import Equity as DomainEquity
from app.portfolio.pricing import enrich_positions_with_price, positions_value
from app.portfolio.risk import position_risk_pct, protective_stop, total_open_risk_pct
from app.signals.engine import drop_malformed_daily_bars

# 2%/6% rule thresholds used by the display fields below (`two_percent_rule_breached`,
# `six_percent_rule_breached`) -- kept in sync by hand with the identical private constants
# in app.portfolio.exits (`_TWO_PERCENT_RULE_THRESHOLD`/`_SIX_PERCENT_RULE_THRESHOLD`), the
# same way exits.py's own constants are hand-kept in sync with docs/Analyse.md §7 rather than
# imported from app.portfolio.risk -- see this task's `decisions` entry.
_TWO_PERCENT_RULE_THRESHOLD = 2.0
_SIX_PERCENT_RULE_THRESHOLD = 6.0

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _ordered_positions(db: Session) -> list[PositionORM]:
    """All held positions in a deterministic order (`entry_date`, then `id` as a tiebreaker
    for same-day entries), used by both GET /api/portfolio and GET /api/portfolio/risk so
    neither relies on incidental SQLite row-return order -- see this task's `decisions`
    entry."""
    return db.query(PositionORM).order_by(PositionORM.entry_date, PositionORM.id).all()


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
    api-portfolio-risk task's `decisions` entry."""
    account = db.get(AccountORM, 1)
    cash = account.cash if account is not None else 0.0

    enriched = enrich_positions_with_price(_ordered_positions(db), provider)
    value = positions_value(enriched)

    positions_out = [
        PositionOut(
            id=e.position.id,
            ticker=e.position.ticker,
            quantity=e.position.quantity,
            avg_cost_basis=e.position.avg_cost_basis,
            entry_date=e.position.entry_date,
            current_price=e.position.current_price,
            unrealized_pnl_pct=e.position.unrealized_pnl_pct,
        )
        for e in enriched
    ]

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
    `current_price`/`unrealized_pnl_pct` are always null here: price enrichment happens on
    read (GET /api/portfolio), not on write, and isn't available until the data-cache task
    lands."""
    ticker = position.ticker.upper()
    existing = db.query(PositionORM).filter(PositionORM.ticker == ticker).one_or_none()

    if existing is None:
        row = PositionORM(
            id=f"pos_{uuid.uuid4().hex[:12]}",
            ticker=ticker,
            quantity=position.quantity,
            avg_cost_basis=position.avg_cost_basis,
            entry_date=position.entry_date,
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
    )


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    operation_id="delete_position",
    summary="Remove a position",
    responses={404: {"model": ErrorDetail, "description": "Position not found"}},
)
def delete_position(position_id: str, db: Session = Depends(get_db)) -> None:
    """Removes a position entirely. There is no partial-quantity reduction endpoint —
    reducing a position means deleting and re-adding it with the new quantity."""
    row = db.get(PositionORM, position_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Position '{position_id}' not found")

    db.delete(row)
    db.commit()


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

    A position is silently excluded from `positions` (and so from `total_open_risk_pct`,
    which only sums positions with a known stop — see `app.portfolio.risk
    .total_open_risk_pct`) whenever its risk can't be computed at all: its current price
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
    its own `close` is NaN, matching `app.portfolio.pricing._latest_close`'s own close-only
    validity rule for that exact bar (which is what `position.current_price` was derived
    from), rather than also requiring open/high/low there — a shape `_latest_close` doesn't
    guard against, and one this pipeline's own downstream reads (`evaluate_exit_flags` and
    everything it calls) never touch for the latest bar anyway. Using the stricter default here
    would silently drop a real latest bar whose close is valid but whose open/high/low haven't
    settled yet, desyncing `position.current_price` from `daily_ohlcv`'s last row and making
    `evaluate_exit_flags` test yesterday's close against today's stop instead of today's — see
    the api-stocks-analysis-nullable-indicators-followups task's `decisions` entry for the full
    reasoning and the regression this reconciles."""
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
        daily_ohlcv = drop_malformed_daily_bars(e.daily_ohlcv, require_full_ohlc_on_latest_bar=False)
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
    # way: an unknown total open risk degrades to 0.0 (and so never breaches the 6% rule)
    # rather than propagating as an unhandled 500, consistent with every other
    # can't-be-computed case this endpoint documents as a silent exclusion.
    try:
        total_risk = total_open_risk_pct(account, stops)
    except ValueError:
        total_risk = 0.0
    six_percent_rule_breached = total_risk > _SIX_PERCENT_RULE_THRESHOLD

    risk_positions: list[RiskPosition] = []
    for e in enriched:
        if e.position.id not in stops:
            continue
        stop = stops[e.position.id]
        try:
            risk_pct = position_risk_pct(e.position, stop, account)
            exit_flags = evaluate_exit_flags(
                e.position, account, daily_by_id[e.position.id], weekly_by_id[e.position.id], total_risk
            )
        except ValueError:
            continue

        risk_positions.append(
            RiskPosition(
                id=e.position.id,
                ticker=e.position.ticker,
                protective_stop=stop,
                position_risk_pct=risk_pct,
                two_percent_rule_breached=risk_pct > _TWO_PERCENT_RULE_THRESHOLD,
                exit_flags=exit_flags,
            )
        )

    return RiskResponse(
        total_open_risk_pct=total_risk,
        six_percent_rule_breached=six_percent_rule_breached,
        positions=risk_positions,
    )
