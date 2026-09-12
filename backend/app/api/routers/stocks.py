from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import AnalysisResponse, ErrorDetail, HistoryResponse

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

# Route bodies are stubs (see the add-api-endpoint skill) — the signatures,
# response_models, and error responses below are real and drive the OpenAPI
# schema the frontend generates its types from (docs/architecture/API.md).
# Keep this contract accurate even while unimplemented: it's what lets
# frontend and backend work proceed in parallel.


@router.get(
    "/{ticker}/history",
    response_model=HistoryResponse,
    operation_id="get_stock_history",
    summary="Get OHLCV price history",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def get_history(
    ticker: str,
    range: str = Query("1y", description="Lookback window, e.g. '1y'"),
    interval: Literal["daily", "weekly"] = Query("daily"),
) -> HistoryResponse:
    """Raw OHLCV bars for charting, served from the SQLite cache (docs/architecture/Backend.md §7)
    and backfilled from yfinance/Stooq on a cache miss. Weekly bars are yfinance's native
    weekly interval, not a manual resample of daily bars, per docs/Analyse.md §9."""
    raise HTTPException(status_code=501, detail="not implemented yet")


@router.get(
    "/{ticker}/analysis",
    response_model=AnalysisResponse,
    operation_id="get_stock_analysis",
    summary="Get the Triple Screen signal, confidence, and indicator breakdown",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        422: {"model": ErrorDetail, "description": "Insufficient history to compute weekly indicators"},
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def get_analysis(ticker: str) -> AnalysisResponse:
    """Runs the full Triple Screen evaluation (tide, wave, trigger, Impulse gate) and the
    weighted confidence score for `ticker` (docs/Analyse.md §2-6). `confidence_breakdown`
    exposes the per-component scores so the signal is auditable, not just a bare number."""
    raise HTTPException(status_code=501, detail="not implemented yet")
