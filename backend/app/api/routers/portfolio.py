from fastapi import APIRouter, HTTPException

from app.api.schemas import ErrorDetail, PortfolioResponse, PositionIn, PositionOut, RiskResponse

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
def get_portfolio() -> PortfolioResponse:
    """All held positions plus account equity (cash + mark-to-market positions value).
    `current_price`/`unrealized_pnl_pct` on each position are enriched from the market
    data cache and are null only if a price fetch for that ticker has failed."""
    raise HTTPException(status_code=501, detail="not implemented yet")


@router.post(
    "/positions",
    response_model=PositionOut,
    status_code=201,
    operation_id="add_position",
    summary="Add or update a position",
)
def add_position(position: PositionIn) -> PositionOut:
    """Creates a position from manual entry / CSV-import data. Duplicate-ticker behavior
    (merge quantity/avg cost vs. reject) is not yet decided — see the
    api-portfolio-add-position task in docs/tasks/ before implementing this handler."""
    raise HTTPException(status_code=501, detail="not implemented yet")


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
