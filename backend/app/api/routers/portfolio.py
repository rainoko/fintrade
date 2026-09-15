import math
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.api.schemas import (
    ErrorDetail,
    Equity,
    PortfolioResponse,
    PositionIn,
    PositionOut,
    RiskResponse,
)
from app.data.base import DataProvider
from app.data.exceptions import DataProviderError
from app.db.models import AccountORM, PositionORM
from app.db.session import get_db

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

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
    task's `decisions` entry."""
    account = db.get(AccountORM, 1)
    cash = account.cash if account is not None else 0.0

    positions_out: list[PositionOut] = []
    positions_value = 0.0
    for row in db.query(PositionORM).all():
        current_price = _latest_close(provider, row.ticker)
        unrealized_pnl_pct = (
            (current_price - row.avg_cost_basis) / row.avg_cost_basis * 100.0
            if current_price is not None
            else None
        )
        if current_price is not None:
            positions_value += row.quantity * current_price

        positions_out.append(
            PositionOut(
                id=row.id,
                ticker=row.ticker,
                quantity=row.quantity,
                avg_cost_basis=row.avg_cost_basis,
                entry_date=row.entry_date,
                current_price=current_price,
                unrealized_pnl_pct=unrealized_pnl_pct,
            )
        )

    return PortfolioResponse(
        equity=Equity(cash=cash, positions_value=positions_value, total=cash + positions_value),
        positions=positions_out,
    )


def _latest_close(provider: DataProvider, ticker: str) -> float | None:
    """Most recent daily close for `ticker`, or None if the fetch failed for any
    reason a `DataProvider` can raise (unknown ticker, insufficient history, or
    the provider being unavailable) -- GET /api/portfolio degrades a single bad
    ticker to a null price rather than failing the whole response, since a
    portfolio commonly holds several positions and one bad price shouldn't hide
    the rest (see this task's `decisions` entry)."""
    try:
        frame = provider.get_daily_ohlcv(ticker)
    except DataProviderError:
        return None
    if frame.empty:
        return None
    return float(frame.iloc[-1]["close"])


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
def delete_position(position_id: str) -> None:
    """Removes a position entirely. There is no partial-quantity reduction endpoint —
    reducing a position means deleting and re-adding it with the new quantity."""
    raise HTTPException(status_code=501, detail="not implemented yet")


@router.get(
    "/risk",
    response_model=RiskResponse,
    operation_id="get_portfolio_risk",
    summary="Get the 2%/6% rule evaluation and per-position exit flags",
)
def get_risk() -> RiskResponse:
    """Per-position protective stop, 2%-rule risk, and exit flags, plus the portfolio-wide
    6%-rule total (docs/Analyse.md §7). `exit_flags` can be non-empty even when the
    corresponding stock's fresh technical signal is HOLD — risk-driven exits are
    independent of entry-signal logic by design."""
    raise HTTPException(status_code=501, detail="not implemented yet")
