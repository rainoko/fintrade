"""Shared mark-to-market price enrichment for portfolio positions.

Extracted out of GET /api/portfolio's handler (app/api/routers/portfolio.py) per the
api-portfolio-get-followups task, once GET /api/portfolio/risk needed the exact same
fetch-current-price-and-degrade-gracefully-per-ticker loop: `app.portfolio.risk
.position_risk_pct`'s precondition is a populated `position.current_price`, and
`app.portfolio.exits.evaluate_exit_flags` needs the same day's `daily_ohlcv` frame the price
was read from -- see the api-portfolio-risk task's `decisions` entry for why the extraction
happened now rather than staying deferred.
"""

from dataclasses import dataclass

import pandas as pd

from app.data.base import DataProvider
from app.data.exceptions import DataProviderError
from app.db.models import PositionORM
from app.portfolio.models import Position


@dataclass(frozen=True)
class EnrichedPosition:
    """A domain `Position` with `current_price`/`unrealized_pnl_pct` populated (both left
    `None` on a failed fetch), plus the `daily_ohlcv` frame the price was read from.

    `daily_ohlcv` is `None` whenever `position.current_price` is `None` (a failed fetch has
    no usable frame to share), and otherwise the *full* frame `get_daily_ohlcv` returned --
    not just its latest row -- so a caller that also needs recent history for this same
    ticker in this same request (e.g. GET /api/portfolio/risk's protective-stop/exit-flag
    computation) can reuse it instead of re-fetching.
    """

    position: Position
    daily_ohlcv: pd.DataFrame | None


def enrich_positions_with_price(
    rows: list[PositionORM], provider: DataProvider
) -> list[EnrichedPosition]:
    """Fetch each row's latest daily close, degrading gracefully per-ticker on failure.

    Mirrors the original GET /api/portfolio behavior (see the api-portfolio-get task's
    `decisions`): a position whose price couldn't be fetched -- unknown ticker, insufficient
    history, the provider unavailable, an empty frame, or a NaN latest close -- gets
    `current_price=None`/`unrealized_pnl_pct=None` rather than falling back to cost basis,
    and its bad price can't NaN-poison a running total (e.g. `positions_value` below) a
    caller sums across positions, since `None` is skipped rather than summed.
    """
    enriched: list[EnrichedPosition] = []
    for row in rows:
        current_price, daily_ohlcv = _latest_close(provider, row.ticker)
        unrealized_pnl_pct = (
            (current_price - row.avg_cost_basis) / row.avg_cost_basis * 100.0
            if current_price is not None
            else None
        )
        enriched.append(
            EnrichedPosition(
                position=Position(
                    id=row.id,
                    ticker=row.ticker,
                    quantity=row.quantity,
                    avg_cost_basis=row.avg_cost_basis,
                    entry_date=row.entry_date,
                    current_price=current_price,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                ),
                daily_ohlcv=daily_ohlcv,
            )
        )
    return enriched


def positions_value(enriched: list[EnrichedPosition]) -> float:
    """Sum of quantity x current_price across `enriched`, skipping any position whose price
    fetch failed (`current_price is None`) rather than treating it as 0 -- matches
    `Equity.positions_value`'s documented "mark-to-market, not cost basis" contract, which a
    position with no known current price simply can't contribute to.
    """
    return sum(
        e.position.quantity * e.position.current_price
        for e in enriched
        if e.position.current_price is not None
    )


def _latest_close(
    provider: DataProvider, ticker: str
) -> tuple[float | None, pd.DataFrame | None]:
    """Most recent daily close for `ticker` plus the frame it came from, or `(None, None)`
    if the fetch failed for any reason a `DataProvider` can raise (unknown ticker,
    insufficient history, or the provider being unavailable), the frame came back empty, or
    the latest close itself is NaN -- see `enrich_positions_with_price`'s docstring. Neither
    provider's daily series is guaranteed NaN-free (only the derived weekly series gets
    `.dropna()`), so the NaN check guards against silently NaN-poisoning any running total a
    caller derives from `current_price` (NaN is contagious under float addition), not just
    this one field.
    """
    try:
        frame = provider.get_daily_ohlcv(ticker)
    except DataProviderError:
        return None, None
    if frame.empty or pd.isna(frame.iloc[-1]["close"]):
        return None, None
    return float(frame.iloc[-1]["close"]), frame
