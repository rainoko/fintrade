"""GET/POST/DELETE /api/watchlist (docs/architecture/API.md).

Each watched ticker is annotated with its live signal/confidence by calling the exact same
`app.signals.engine.analyse()` that `GET /api/stocks/{ticker}/analysis` uses -- no
separately-implemented "is this a buy" check, per this task's description ("one place,
testable once"). See this task's `decisions` entry for the nullable-signal-on-failure and
idempotent-duplicate-add choices.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.api.schemas import ErrorDetail, WatchlistItemIn, WatchlistItemOut, WatchlistResponse
from app.data.base import DataProvider
from app.data.exceptions import DataProviderError
from app.db.models import WatchlistItemORM
from app.db.session import get_db
from app.signals.engine import SignalResult, analyse

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _utcnow() -> datetime:
    """Naive UTC 'now', matching how `WatchlistItemORM.added_at` / `OHLCVCacheORM.fetched_at`
    (app/data/cache.py's `_utcnow`) are stored/compared."""
    return datetime.now(UTC).replace(tzinfo=None)


def _compute_signal(ticker: str, provider: DataProvider) -> SignalResult | None:
    """Runs the same fetch-then-`analyse()` pipeline `GET /api/stocks/{ticker}/analysis` uses
    for a single ticker, returning `None` instead of raising if the signal can't be computed
    right now (unknown/delisted ticker, insufficient history, or the data provider being
    unavailable -- any `DataProviderError`) -- see this task's `decisions` entry for why a
    per-ticker failure degrades to a nullable field on that entry rather than failing the
    whole `GET /api/watchlist` list or silently excluding the ticker from it (both of which
    would hide from the caller that a ticker they're watching couldn't be evaluated).

    Deliberately narrow: only `DataProviderError` (the documented, expected failure mode for
    a market-data fetch) is caught here, not a bare `except Exception`, so a genuine bug in
    `analyse()` itself still surfaces as a loud 500 in tests/CI instead of being silently
    swallowed into a null field.

    Unlike `stocks.py`'s `get_analysis` (which pre-filters `daily_ohlcv` with
    `drop_malformed_daily_bars` itself because it needs the cleaned frame afterward to derive
    `as_of`), this function never uses `daily_ohlcv` again after passing it to `analyse()` --
    and `analyse()` already runs `drop_malformed_daily_bars` internally as its first step, so
    filtering here first would just be a redundant full-DataFrame pass per watched ticker on
    every `GET /api/watchlist` request. `analyse()` is left to do it once."""
    try:
        daily_ohlcv = provider.get_daily_ohlcv(ticker)
        weekly_ohlcv = provider.get_weekly_ohlcv(ticker)
    except DataProviderError:
        return None

    return analyse(ticker, daily_ohlcv, weekly_ohlcv)


def _to_out(row: WatchlistItemORM, result: SignalResult | None) -> WatchlistItemOut:
    return WatchlistItemOut(
        ticker=row.ticker,
        added_at=row.added_at,
        signal=result.signal if result is not None else None,
        confidence=result.confidence if result is not None else None,
        confidence_band=result.confidence_band if result is not None else None,
    )


@router.get(
    "",
    response_model=WatchlistResponse,
    operation_id="get_watchlist",
    summary="List every watched ticker with its current signal",
)
def get_watchlist(
    db: Session = Depends(get_db),
    provider: DataProvider = Depends(get_data_provider),
) -> WatchlistResponse:
    """Every ticker on the watchlist, each annotated with its current BUY/SELL/HOLD signal
    and confidence by re-running the same Triple Screen signal engine
    `GET /api/stocks/{ticker}/analysis` uses (`app.signals.engine.analyse`,
    docs/Analyse.md §5) -- so "does the watchlist signal a buy" always agrees with what a
    direct lookup of that ticker's analysis page would say, with no second implementation of
    the buy check to drift out of sync.

    `signal`/`confidence`/`confidence_band` are null together on an entry whose signal
    couldn't be computed right now (unknown/delisted ticker, insufficient history, or the
    data provider being unavailable) -- this endpoint never fails or drops an entry just
    because one watched ticker's data is temporarily/permanently unavailable; see this
    task's `decisions` entry. Ordered by `added_at` (oldest first), then `ticker` as a
    tiebreaker for same-instant adds, mirroring `GET /api/portfolio`'s deterministic
    ordering convention (`app.api.routers.portfolio._ordered_positions`)."""
    rows = (
        db.query(WatchlistItemORM)
        .order_by(WatchlistItemORM.added_at, WatchlistItemORM.ticker)
        .all()
    )
    return WatchlistResponse(
        items=[_to_out(row, _compute_signal(row.ticker, provider)) for row in rows]
    )


@router.post(
    "",
    response_model=WatchlistItemOut,
    status_code=201,
    operation_id="add_watchlist_item",
    summary="Add a ticker to the watchlist",
)
def add_watchlist_item(item: WatchlistItemIn, db: Session = Depends(get_db)) -> WatchlistItemOut:
    """Adds `ticker` to the watchlist. Adding a ticker that's already watched is a no-op:
    the existing entry (with its original `added_at`) is returned unchanged, still with
    `201`, rather than creating a duplicate row or rejecting with `409`/`422` -- see this
    task's `decisions` entry for the full rationale.

    `signal`/`confidence`/`confidence_band` are always `null` in this response: annotation
    happens on read (`GET /api/watchlist`), not on write -- mirroring
    `POST /api/portfolio/positions`'s `current_price`/`unrealized_pnl_pct`
    null-on-write convention."""
    ticker = item.ticker.upper()
    row = db.get(WatchlistItemORM, ticker)
    if row is None:
        row = WatchlistItemORM(ticker=ticker, added_at=_utcnow())
        db.add(row)
        db.commit()
        db.refresh(row)

    return _to_out(row, None)


@router.delete(
    "/{ticker}",
    status_code=204,
    operation_id="delete_watchlist_item",
    summary="Remove a ticker from the watchlist",
    responses={404: {"model": ErrorDetail, "description": "Ticker not on the watchlist"}},
)
def delete_watchlist_item(ticker: str, db: Session = Depends(get_db)) -> None:
    """Removes `ticker` from the watchlist entirely. `ticker` is normalized to uppercase,
    matching every other `/api/watchlist` and `/api/stocks/*` route."""
    ticker = ticker.upper()
    row = db.get(WatchlistItemORM, ticker)
    if row is None:
        raise HTTPException(status_code=404, detail=f"'{ticker}' is not on the watchlist")

    db.delete(row)
    db.commit()
