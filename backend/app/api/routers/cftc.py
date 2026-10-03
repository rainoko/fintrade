"""GET /api/cftc/cot (docs/tasks/backend-cftc-cot-data.json).

CFTC Commitments of Traders (COT) positioning for a small, fixed set of major futures
markets (Euro, Yen, Oil, Gold, Bonds -- matching the ch. 57 daily-homework idea's own list),
per docs/ideas.md's ch. 37 entry. This is a genuinely separate, informational surface --
futures-market context, not something that plugs into any per-stock-ticker signal the way
insider clusters or short interest do -- so this router has no dependency on, and isn't
referenced by, anything in `app.signals`/`app.portfolio`. See this task's `decisions` entry.
"""

from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_cftc_cot_provider
from app.api.schemas import CFTCCOTMarketOut, CFTCCOTResponse, CFTCMarketKey, ErrorDetail
from app.data.cftc_cot_cache import CFTCCOTCache
from app.data.cftc_cot_provider import COT_MARKETS, CFTCCOTProvider, COTWeeklyReport, cot_index
from app.data.exceptions import DataProviderUnavailableError
from app.db.session import get_db

router = APIRouter(prefix="/api/cftc", tags=["cftc"])


def _to_market_out(market_key: CFTCMarketKey, reports: list[COTWeeklyReport]) -> CFTCCOTMarketOut:
    # `reports` is most-recent-first (CFTCCOTProvider.get_all_recent's own contract);
    # `latest` is this market's current week, `reports` as a whole is the trailing window
    # `cot_index` reads "historical norms" from -- including `latest` itself, matching
    # that indicator's standard definition.
    latest = reports[0]
    commercial_net_history = [r.commercial_net for r in reports]
    large_speculator_net_history = [r.large_speculator_net for r in reports]
    small_speculator_net_history = [r.small_speculator_net for r in reports]

    return CFTCCOTMarketOut(
        market_key=market_key,
        display_name=latest.market_and_exchange_name,
        report_date=latest.report_date,
        open_interest=latest.open_interest,
        commercial_long=latest.commercial_long,
        commercial_short=latest.commercial_short,
        commercial_net=latest.commercial_net,
        large_speculator_long=latest.large_speculator_long,
        large_speculator_short=latest.large_speculator_short,
        large_speculator_net=latest.large_speculator_net,
        small_speculator_long=latest.small_speculator_long,
        small_speculator_short=latest.small_speculator_short,
        small_speculator_net=latest.small_speculator_net,
        weeks_of_history=len(reports),
        commercial_cot_index_52w=cot_index(latest.commercial_net, commercial_net_history),
        large_speculator_cot_index_52w=cot_index(latest.large_speculator_net, large_speculator_net_history),
        small_speculator_cot_index_52w=cot_index(latest.small_speculator_net, small_speculator_net_history),
    )


@router.get(
    "/cot",
    response_model=CFTCCOTResponse,
    operation_id="get_cftc_cot",
    summary="Current + recent CFTC Commitments of Traders positioning for a fixed set of major futures markets",
    responses={
        503: {
            "model": ErrorDetail,
            "description": "The CFTC's public Socrata data endpoint itself failed (network error, "
            "unexpected/malformed response) or returned no data for one of this app's fixed markets.",
        },
    },
)
def get_cftc_cot(
    provider: CFTCCOTProvider = Depends(get_cftc_cot_provider),
    db: Session = Depends(get_db),
) -> CFTCCOTResponse:
    """Elder ch. 37's Commitments of Traders framing -- follow commercials (historically the
    successful group), fade small speculators (historically the unsuccessful group), and
    read current positioning against historical norms rather than an absolute level --
    applied to a small, fixed set of major futures markets (Euro, Yen, Oil, Gold, Bonds,
    matching the ch. 57 daily-homework idea's own list; `app.data.cftc_cot_provider.
    COT_MARKETS`).

    Served from a DB-backed cache (`app.data.cftc_cot_cache.CFTCCOTCache`,
    docs/tasks/backend-cftc-cot-caching-scheduler.json) kept fresh by a weekly scheduled
    background refresh (`app.main._cftc_cot_refresh_loop`) -- matching the CFTC's own
    weekly publication cadence, this endpoint deliberately does NOT re-check staleness or
    re-fetch live on every call once the cache is populated (see this task's `decisions`
    entry for why that's structurally correct here, unlike this app's other, TTL-based
    caches). It only falls back to a live CFTC fetch on a genuine cache miss -- an empty
    cache, e.g. before the scheduled refresh loop has run even once since this app started.

    Raises `503` if a cache-miss live fetch itself fails, or unexpectedly returns no rows
    for one of this app's fixed contract codes -- there is no per-market "not found" case
    the way there is for an arbitrary user-supplied stock ticker, since these are all long-
    established, actively-traded futures contracts.
    """
    cache = CFTCCOTCache(db)
    reports_by_market = cache.get_cached_reports()
    if reports_by_market is None:
        try:
            reports_by_market = provider.get_all_recent()
        except DataProviderUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        cache.refresh(reports_by_market)

    return CFTCCOTResponse(
        markets=[
            # `COT_MARKETS`' keys are always this app's own fixed 5-market set (defined
            # alongside `CFTCMarketKey`'s own Literal, both meant to stay in lockstep --
            # see this task's `decisions` entry) -- `str` in `COT_MARKETS`'s own type
            # (data-layer code has no reason to depend on an api-layer Literal, matching
            # `GatewayState`/`IBKRGatewayState`'s identical split definition) is narrowed
            # here for the response schema.
            _to_market_out(cast(CFTCMarketKey, market_key), reports_by_market[market_key])
            for market_key in COT_MARKETS
        ]
    )
