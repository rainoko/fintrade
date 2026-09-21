"""GET /api/ibkr/status (docs/tasks/backend-ibkr-status-endpoint.json) +
GET /api/ibkr/scanner/params, POST /api/ibkr/scanner/run (docs/tasks/backend-market-scanner.json).

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
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_ibkr_provider
from app.api.schemas import (
    ErrorDetail,
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

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"])

_DISABLED_DETAIL = "IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."


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

    categories = params.get("scan_type_list") if isinstance(params, dict) else None
    return IBKRScannerParamsResponse(state="available", detail=None, categories=categories or [])


@router.post(
    "/scanner/run",
    response_model=IBKRScannerRunResponse,
    operation_id="run_ibkr_scanner",
    summary="Run an IBKR market scan, or report why the scanner is unavailable",
    responses={
        429: {"model": ErrorDetail, "description": "Scanner run rate limit (1 request/second) exceeded"},
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
    otherwise-available* scanner, so it's surfaced as `429`, not folded into `state`. A
    scanner-run call that itself fails transiently against an otherwise-`available` gateway
    (see `_resolve_scanner_unavailable`) is likewise surfaced as a `503`, not folded into
    `state`.
    """
    if provider is None:
        return IBKRScannerRunResponse(state="disabled", detail=_DISABLED_DETAIL, results=None)

    try:
        results = provider.run_scanner(body.scan_config)
    except IBKRRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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
