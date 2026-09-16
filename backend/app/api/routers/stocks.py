from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_data_provider
from app.api.schemas import (
    AnalysisResponse,
    ConfidenceBreakdownItem,
    ErrorDetail,
    HistoryResponse,
    OHLCVBar,
)
from app.data.base import DataProvider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.signals.engine import analyse

# Accepted `range` query values: '<N>d' | '<N>w' | '<N>m' | '<N>y' (e.g. '1y', '6m', '90d'),
# or the literal 'max' for full available history. Matches the one example API.md gives
# ('1y') and mirrors yfinance's own period vocabulary (docs/architecture/API.md
# #get-apistocksstickerhistory) without accepting yfinance's other period spellings
# ('ytd', '5d' with no unit, etc.) that this endpoint doesn't document. See this task's
# `decisions` entry.
_RANGE_PATTERN = r"^(max|\d+[dwmy])$"

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
        422: {
            "description": "Either of two distinct shapes, both under HTTP 422: `range` doesn't "
            "match the accepted pattern (FastAPI's standard HTTPValidationError — `detail` is a "
            "list of per-field errors), or the requested weekly interval has fewer than 26 weeks "
            "of history (`detail` is a single string, ErrorDetail) — same dual-shape pattern as "
            "`POST /api/portfolio/positions`.",
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
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def get_history(
    ticker: str,
    range: str = Query(
        "1y",
        pattern=_RANGE_PATTERN,
        description="Lookback window: '<N>d' | '<N>w' | '<N>m' | '<N>y' (e.g. '1y', '6m', '90d'), "
        "or 'max' for full available history. Trimmed from the most recent bar actually "
        "returned, not from today's date.",
    ),
    interval: Literal["daily", "weekly"] = Query("daily"),
    provider: DataProvider = Depends(get_data_provider),
) -> HistoryResponse:
    """Raw OHLCV bars for charting, served from the SQLite cache (docs/architecture/Backend.md §7)
    and backfilled from yfinance/Stooq on a cache miss. Weekly bars are yfinance's native
    weekly interval, not a manual resample of daily bars, per docs/Analyse.md §9.

    `ticker` is normalized to uppercase, matching `GET /api/stocks/{ticker}/analysis` and
    `POST /api/portfolio/positions`. Only the interval actually requested is fetched (unlike
    `/analysis`, which always needs both) -- so a `weekly`-interval request is the only way
    this endpoint can itself raise the same <26-week `InsufficientHistoryError` -> 422 that
    `/analysis`'s weekly fetch enforces (`app.data.yfinance_provider.YFinanceProvider._MIN_WEEKLY_BARS`);
    see this task's `decisions` entry for why that's surfaced here too rather than only for
    computed indicators."""
    ticker = ticker.upper()
    try:
        if interval == "weekly":
            ohlcv = provider.get_weekly_ohlcv(ticker)
        else:
            ohlcv = provider.get_daily_ohlcv(ticker)
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    ohlcv = _trim_to_range(ohlcv, range)

    bars = [
        OHLCVBar(
            date=idx.date() if hasattr(idx, "date") else idx,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for idx, row in ohlcv.iterrows()
    ]
    return HistoryResponse(ticker=ticker, interval=interval, bars=bars)


def _trim_to_range(ohlcv: pd.DataFrame, range_param: str) -> pd.DataFrame:
    """Trim `ohlcv` (already the provider's full cached/fetched history -- the `DataProvider`
    protocol itself takes no date-range argument, see app/data/cache.py's module docstring) to
    the trailing `range_param` window.

    Anchored on the most recent bar actually present in `ohlcv`, not on today's wall-clock
    date: the cache can be up to 24h stale (app/data/cache.py's `_CACHE_TTL`), and a
    delisted/thinly-traded ticker's history may not extend to the present at all -- anchoring
    on "today" in either case would silently return fewer bars than the requested range implies.
    """
    if range_param == "max" or ohlcv.empty:
        return ohlcv
    count = int(range_param[:-1])
    unit = range_param[-1]
    anchor = ohlcv.index[-1]
    if unit == "d":
        # `pd.DateOffset`, not `pd.Timedelta`, for every unit here -- `pd.Timedelta(days=...)`
        # / `pd.Timedelta(weeks=...)` alone (no other kwarg) trip a spurious NumPy
        # "'generic' unit" DeprecationWarning on this pandas/NumPy pairing even though the
        # arithmetic itself is correct; `DateOffset` sidesteps it and reads the same.
        cutoff = anchor - pd.DateOffset(days=count)
    elif unit == "w":
        cutoff = anchor - pd.DateOffset(weeks=count)
    elif unit == "m":
        cutoff = anchor - pd.DateOffset(months=count)
    else:  # "y"
        cutoff = anchor - pd.DateOffset(years=count)
    return ohlcv[ohlcv.index > cutoff]


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
