from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_data_provider
from app.api.schemas import AnalysisResponse, ConfidenceBreakdownItem, ErrorDetail, HistoryResponse
from app.data.base import DataProvider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.signals.engine import analyse

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
def get_analysis(
    ticker: str,
    provider: DataProvider = Depends(get_data_provider),
) -> AnalysisResponse:
    """Runs the full Triple Screen evaluation (tide, wave, trigger, Impulse gate) and the
    weighted confidence score for `ticker` (docs/Analyse.md §2-6). `confidence_breakdown`
    exposes the per-component scores so the signal is auditable, not just a bare number.

    `ticker` is normalized to uppercase (mirrors `POST /api/portfolio/positions`'s handling
    of the same field) before being passed to the data provider and echoed back in the
    response. Daily and weekly OHLCV are fetched via the SQLite-backed cache
    (`app.data.cache.CachedDataProvider`, docs/architecture/Backend.md §7); the weekly fetch
    is what actually enforces the <26-week-history -> 422 rule
    (`app.data.yfinance_provider.YFinanceProvider._MIN_WEEKLY_BARS`) -- this handler adds no
    separate minimum-history check of its own, matching `app.signals.engine.analyse`'s own
    documented degrade-gracefully-to-HOLD behavior for a short/empty daily series (see this
    task's `decisions` entry)."""
    ticker = ticker.upper()
    try:
        daily_ohlcv = provider.get_daily_ohlcv(ticker)
        weekly_ohlcv = provider.get_weekly_ohlcv(ticker)
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = analyse(ticker, daily_ohlcv, weekly_ohlcv)

    latest_bar = daily_ohlcv.index[-1] if len(daily_ohlcv) > 0 else weekly_ohlcv.index[-1]
    as_of = latest_bar.date() if hasattr(latest_bar, "date") else latest_bar

    return AnalysisResponse(
        ticker=ticker,
        as_of=as_of,
        signal=result.signal,
        confidence=result.confidence,
        confidence_band=result.confidence_band,
        screens=result.screens,
        confidence_breakdown=[
            ConfidenceBreakdownItem(component=c.component, weight=c.weight, score=c.score)
            for c in result.breakdown
        ],
        indicators=result.indicators,
    )
