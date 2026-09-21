"""GET /api/ibkr/status (docs/tasks/backend-ibkr-status-endpoint.json) +
GET /api/ibkr/scanner/params, POST /api/ibkr/scanner/run (docs/tasks/backend-market-scanner.json) +
POST /api/ibkr/breadth/snapshot (docs/tasks/backend-market-breadth-indicators.json).

`/status` was the first route in the app to consume `app.api.dependencies.get_ibkr_provider`
at all -- it exists so the app (and, later, a frontend indicator) can surface "IBKR:
connected / not authenticated / gateway down / disabled" without any route needing to know
how `IBKRProvider.get_gateway_status()` itself works.

The scanner routes are the market-scanning feature docs/ideas.md's "Market scanning (ch. 56)"
entry describes: IBKR's own predefined scan categories (52-week-high/low, hot-by-volume, top
% gainers/losers, etc.) run broker-side, for discovering candidates outside the user's
existing watchlist -- distinct from that watchlist and from the ticker detail view, neither
of which scan a broad universe at all. Both scanner routes reuse `/status`'s exact
availability pattern (a `state` value on a normal `200` response, never an HTTP error, for
"IBKR isn't enabled/available right now") rather than inventing a second one -- see this
task's `decisions` entry.

`/breadth/snapshot` is Elder ch. 34-36's real, broad-market breadth indicators (NH-NL,
Advance/Decline) -- distinct from the personal-watchlist-only `GET /api/watchlist/breadth`
proxy. It records (once per calendar day) `len(IBKRProvider.run_scanner(...))` for one
caller-labeled `series_key`, and returns 5-day/20-day rolling sums over that series' own
accumulated history (`app.db.models.IBKRBreadthSnapshotORM`) -- a bounded IBKR-scanner-result-
count approximation, not a literal full-market count; see this task's `decisions` entry for
the research finding that drove this scope (IBKR's scanner returns a ranked, capped shortlist
of matching contracts, never a genuine full-market count or percentage) and
docs/Analyse.md's "IBKR-scanner breadth approximation" section for the full caveat.
"""

import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_ibkr_provider
from app.api.schemas import (
    ErrorDetail,
    IBKRBreadthSnapshotRequest,
    IBKRBreadthSnapshotResponse,
    IBKRGatewayState,
    IBKRScannerParamsResponse,
    IBKRScannerResultOut,
    IBKRScannerRunRequest,
    IBKRScannerRunResponse,
    IBKRStatusResponse,
)
from app.data.ibkr_provider import (
    GatewayStatus,
    IBKRProvider,
    IBKRRateLimitedError,
    IBKRUnavailableError,
)
from app.db.models import IBKRBreadthSnapshotORM
from app.db.session import get_db
from app.time_utils import today, utcnow

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"])

_DISABLED_DETAIL = "IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."

# ch. 34's own two rolling windows over the daily figure: "weekly NH-NL" (a 5-trading-day
# moving total) and "20-day NH-NL" (a rolling monthly look-back) -- see this task's
# `decisions` entry for why no other window is added.
_ROLLING_WINDOW_DAYS = (5, 20)
_MAX_ROLLING_WINDOW_DAYS = max(_ROLLING_WINDOW_DAYS)


@router.get(
    "/status",
    response_model=IBKRStatusResponse,
    operation_id="get_ibkr_status",
    summary="Whether the optional IBKR Client Portal Gateway integration is usable right now",
)
def get_ibkr_status(provider: IBKRProvider | None = Depends(get_ibkr_provider)) -> IBKRStatusResponse:
    """Reports the IBKR gateway's connection state -- 'disabled' when
    `Settings.ibkr_enabled` is `False` (this app's default; `get_ibkr_provider` yields
    `None` in exactly that case, so no attempt to reach a gateway is made at all), otherwise
    whatever `IBKRProvider.get_gateway_status()` reports ('available' / 'gateway_unreachable'
    / 'not_authenticated').

    Never raises for any gateway state: `get_gateway_status()` itself never raises (its own
    docstring's contract -- every failure mode it can observe is represented as a
    `GatewayStatus` value instead of an exception), and this handler adds no failure mode of
    its own on top of that.
    """
    if provider is None:
        return IBKRStatusResponse(state="disabled", detail=_DISABLED_DETAIL)

    status = provider.get_gateway_status()
    return IBKRStatusResponse(state=status.state, detail=status.detail)


def _resolve_scanner_unavailable(provider: IBKRProvider, exc: IBKRUnavailableError) -> GatewayStatus:
    """Shared `except IBKRUnavailableError` handling for both scanner routes.

    `IBKRUnavailableError` is raised for two genuinely different reasons that share one
    exception type (see `IBKRProvider._request`/`_require_available`): the gateway/session
    itself isn't `available` (checked *before* the scanner call is even attempted), or the
    scanner-specific call itself failed transiently against a gateway that otherwise is
    `available` (a non-200 response, transport error, or unparseable body from
    `/iserver/scanner/params`/`/iserver/scanner/run` specifically). A fresh
    `get_gateway_status()` call only re-checks the former (it hits the unrelated
    `/iserver/auth/status` endpoint) -- so on the latter, that fresh check still reports
    `available`, and returning `state: "available"` with `categories`/`results` left
    `null` would violate this schema's own documented "non-null iff `state` ==
    'available'" invariant (see this task's `review` finding). Raises `HTTPException(503)`
    in exactly that disagreeing case (the standard "service temporarily unavailable" status
    for a transient, single-call failure -- distinct from `429`'s "you're calling too fast"
    and from the `state` values' "this feature isn't usable at all right now"); otherwise
    returns the resolved `GatewayStatus` for the caller to build its normal `state`-based
    response from.
    """
    status = provider.get_gateway_status()
    if status.state == "available":
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return status


def _rate_limited_http_exception(exc: IBKRRateLimitedError) -> HTTPException:
    """Shared `except IBKRRateLimitedError` handling for `run_ibkr_scanner` and
    `record_ibkr_breadth_snapshot` (both eventually call `IBKRProvider.run_scanner`, the
    only method this client-side rate limit applies to).

    `exc.retry_after` was previously discarded -- available only embedded in `detail`'s
    free-text sentence, whose wording isn't a stable API contract a caller can parse. Also
    surfaces it as the standard `Retry-After` response header (RFC 9110 §10.2.3), rounded up
    to a whole second (the header's own unit) so a caller never retries a fraction of a
    second too early.
    """
    retry_after_seconds = math.ceil(exc.retry_after)
    return HTTPException(
        status_code=429,
        detail=str(exc),
        headers={"Retry-After": str(retry_after_seconds)},
    )


@router.get(
    "/scanner/params",
    response_model=IBKRScannerParamsResponse,
    operation_id="get_ibkr_scanner_params",
    summary="The market scanner's available scan categories, or why the scanner is unavailable",
    responses={
        503: {
            "model": ErrorDetail,
            "description": "The scanner-params call itself failed transiently (not a gateway/session "
            "unavailability -- see GET /api/ibkr/status for that)",
        }
    },
)
def get_ibkr_scanner_params(
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
) -> IBKRScannerParamsResponse:
    """Lists IBKR's own predefined scan categories (`IBKRProvider.get_scanner_params`'s
    `scan_type_list`, e.g. 52-week-high/low, hot-by-volume, top % gainers/losers) so a
    caller can build a `POST /api/ibkr/scanner/run` request -- docs/ideas.md's ch. 56
    market-scanning entry.

    'disabled' when IBKR isn't enabled at all (no gateway call attempted). Otherwise,
    `IBKRProvider.get_scanner_params()` is tried directly (itself served from its own
    15-minute cache on a hit, per this task's "don't add a second, conflicting throttle
    layer" requirement) -- only on an `IBKRUnavailableError` (a cache miss) does this
    handler make the one extra `get_gateway_status()` call needed to report *which*
    unavailable state applies, instead of parsing that information back out of the
    exception's message string. If that fresh check disagrees with the exception (gateway
    reports `available` even though the scanner-params call itself just failed), this is a
    genuine transient failure of this specific call, not a `state`-shaped unavailability --
    see `_resolve_scanner_unavailable` -- and is raised as a `503` instead.
    """
    if provider is None:
        return IBKRScannerParamsResponse(state="disabled", detail=_DISABLED_DETAIL, categories=None)

    try:
        params = provider.get_scanner_params()
    except IBKRUnavailableError as exc:
        status = _resolve_scanner_unavailable(provider, exc)
        return IBKRScannerParamsResponse(state=status.state, detail=status.detail, categories=None)

    return IBKRScannerParamsResponse(
        state="available", detail=None, categories=params.get("scan_type_list") or []
    )


@router.post(
    "/scanner/run",
    response_model=IBKRScannerRunResponse,
    operation_id="run_ibkr_scanner",
    summary="Run an IBKR market scan, or report why the scanner is unavailable",
    responses={
        429: {
            "model": ErrorDetail,
            "description": "Scanner run rate limit (1 request/second) exceeded -- retry after the "
            "number of seconds in the `Retry-After` response header",
        },
        503: {
            "model": ErrorDetail,
            "description": "The scanner-run call itself failed transiently (not a gateway/session "
            "unavailability -- see GET /api/ibkr/status for that)",
        },
    },
)
def run_ibkr_scanner(
    body: IBKRScannerRunRequest,
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
) -> IBKRScannerRunResponse:
    """Runs `body.scan_config` through `IBKRProvider.run_scanner` -- docs/ideas.md's ch. 56
    market-scanning entry's "near-term, using what's already half-built" option: IBKR's own
    predefined scan categories run broker-side across their whole market universe, not this
    app's own signal engine run over a downloaded ticker universe (a separate, much larger
    idea, explicitly out of scope here -- see this task's `description`).

    'disabled'/`gateway_unreachable`/`not_authenticated` states behave exactly like
    `GET /api/ibkr/scanner/params` -- a normal `200` response, never an HTTP error. Being
    rate-limited (more than 1 request/second since this process's own last scan run,
    enforced client-side by `IBKRProvider` itself -- this handler adds no second, competing
    throttle) is different: it's a genuine, actionable, transient error for an *enabled and
    otherwise-available* scanner, so it's surfaced as `429`, not folded into `state` -- with
    the exact retry delay `IBKRRateLimitedError` already computed exposed via the standard
    `Retry-After` header (see `_rate_limited_http_exception`), not just embedded in `detail`'s
    free-text sentence. A scanner-run call that itself fails transiently against an
    otherwise-`available` gateway (see `_resolve_scanner_unavailable`) is likewise surfaced as
    a `503`, not folded into `state`.
    """
    if provider is None:
        return IBKRScannerRunResponse(state="disabled", detail=_DISABLED_DETAIL, results=None)

    try:
        results = provider.run_scanner(body.scan_config)
    except IBKRRateLimitedError as exc:
        raise _rate_limited_http_exception(exc) from exc
    except IBKRUnavailableError as exc:
        status = _resolve_scanner_unavailable(provider, exc)
        return IBKRScannerRunResponse(state=status.state, detail=status.detail, results=None)

    return IBKRScannerRunResponse(
        state="available",
        detail=None,
        results=[
            IBKRScannerResultOut(conid=r.conid, symbol=r.symbol, company_name=r.company_name, rank=r.rank)
            for r in results
        ],
    )


def _unavailable_breadth_response(
    series_key: str, state: IBKRGatewayState, detail: str | None
) -> IBKRBreadthSnapshotResponse:
    return IBKRBreadthSnapshotResponse(state=state, detail=detail, series_key=series_key)


@router.post(
    "/breadth/snapshot",
    response_model=IBKRBreadthSnapshotResponse,
    operation_id="record_ibkr_breadth_snapshot",
    summary="Record (or fetch) today's IBKR-scanner-based breadth count for one series, with rolling sums",
    responses={
        429: {
            "model": ErrorDetail,
            "description": "Scanner run rate limit (1 request/second) exceeded -- retry after the "
            "number of seconds in the `Retry-After` response header",
        },
        503: {
            "model": ErrorDetail,
            "description": "The scanner-run call itself failed transiently (not a gateway/session "
            "unavailability -- see GET /api/ibkr/status for that)",
        },
    },
)
def record_ibkr_breadth_snapshot(
    body: IBKRBreadthSnapshotRequest,
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
    db: Session = Depends(get_db),
) -> IBKRBreadthSnapshotResponse:
    """Elder ch. 34-36's real, broad-market breadth indicators (NH-NL, Advance/Decline),
    approximated via the IBKR scanner -- distinct from `GET /api/watchlist/breadth`'s
    personal-watchlist-only Tide aggregate.

    `body.series_key` is an opaque, caller-chosen label for one side of a breadth reading
    (e.g. `"nh"`/`"nl"`, `"adv"`/`"dec"`) -- this app doesn't hardcode which IBKR scan-type
    code corresponds to which side (see this task's `decisions` entry); the caller supplies
    `body.scan_config` (same shape as `POST /api/ibkr/scanner/run`) and combines two labeled
    readings into a spread itself (e.g. `nh.rolling_5d - nl.rolling_5d`).

    At most one scan is run per `series_key` per calendar day: if today's row already exists
    (`app.db.models.IBKRBreadthSnapshotORM`), it's served directly and `body.scan_config` is
    ignored -- not a stateless per-request computation, since ch. 34's rolling windows need an
    accumulated daily history, and re-scanning on every request would also needlessly spend
    IBKR's rate-limited `run_scanner` calls. `rolling_5d`/`rolling_20d` sum `count` over this
    series' most recent recorded days (ending today), null until enough days exist
    (`days_recorded >= 5`/`20` respectively) rather than a misleadingly partial sum.

    'disabled'/`gateway_unreachable`/`not_authenticated` states behave exactly like
    `POST /api/ibkr/scanner/run` -- a normal `200` response, never an HTTP error, with every
    other field null. Being rate-limited or a transient scanner-call failure against an
    otherwise-`available` gateway are surfaced as `429`/`503` respectively, exactly like
    `POST /api/ibkr/scanner/run` -- both only reachable on a cache miss (today's first
    request for this `series_key`), since a cache hit never calls the scanner at all.
    """
    if provider is None:
        return _unavailable_breadth_response(body.series_key, "disabled", _DISABLED_DETAIL)

    snapshot_date = today()
    row = db.get(IBKRBreadthSnapshotORM, (body.series_key, snapshot_date))
    if row is None:
        try:
            results = provider.run_scanner(body.scan_config)
        except IBKRRateLimitedError as exc:
            raise _rate_limited_http_exception(exc) from exc
        except IBKRUnavailableError as exc:
            status = _resolve_scanner_unavailable(provider, exc)
            return _unavailable_breadth_response(body.series_key, status.state, status.detail)

        row = IBKRBreadthSnapshotORM(
            series_key=body.series_key,
            snapshot_date=snapshot_date,
            count=len(results),
            recorded_at=utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    days_recorded = (
        db.query(func.count(IBKRBreadthSnapshotORM.snapshot_date))
        .filter(IBKRBreadthSnapshotORM.series_key == body.series_key)
        .scalar()
        or 0
    )
    recent_counts = [
        c
        for (c,) in db.query(IBKRBreadthSnapshotORM.count)
        .filter(IBKRBreadthSnapshotORM.series_key == body.series_key)
        .order_by(IBKRBreadthSnapshotORM.snapshot_date.desc())
        .limit(_MAX_ROLLING_WINDOW_DAYS)
        .all()
    ]

    return IBKRBreadthSnapshotResponse(
        state="available",
        detail=None,
        series_key=body.series_key,
        snapshot_date=snapshot_date,
        count=row.count,
        days_recorded=days_recorded,
        rolling_5d=sum(recent_counts[:5]) if days_recorded >= 5 else None,
        rolling_20d=sum(recent_counts[:20]) if days_recorded >= 20 else None,
    )
