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
from app.data.ibkr_provider import IBKRProvider, IBKRRateLimitedError, IBKRUnavailableError

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


@router.get(
    "/scanner/params",
    response_model=IBKRScannerParamsResponse,
    operation_id="get_ibkr_scanner_params",
    summary="The market scanner's available scan categories, or why the scanner is unavailable",
)
def get_ibkr_scanner_params(
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
) -> IBKRScannerParamsResponse:
    """Lists IBKR's own predefined scan categories (`IBKRProvider.get_scanner_params`'s
    `scan_type_list`, e.g. 52-week-high/low, hot-by-volume, top % gainers/losers) so a
    caller can build a `POST /api/ibkr/scanner/run` request -- docs/ideas.md's ch. 56
    market-scanning entry.

    Never raises: mirrors `GET /api/ibkr/status`'s 'never fails, degrade to a `state`
    value' contract exactly. 'disabled' when IBKR isn't enabled at all (no gateway call
    attempted). Otherwise, `IBKRProvider.get_scanner_params()` is tried directly (itself
    served from its own 15-minute cache on a hit, per this task's "don't add a second,
    conflicting throttle layer" requirement) -- only on an `IBKRUnavailableError` (a cache
    miss against a gateway that isn't `available`) does this handler make the one extra
    `get_gateway_status()` call needed to report *which* unavailable state applies,
    instead of parsing that information back out of the exception's message string.
    """
    if provider is None:
        return IBKRScannerParamsResponse(state="disabled", detail=_DISABLED_DETAIL, categories=None)

    try:
        params = provider.get_scanner_params()
    except IBKRUnavailableError:
        status = provider.get_gateway_status()
        return IBKRScannerParamsResponse(state=status.state, detail=status.detail, categories=None)

    categories = params.get("scan_type_list") if isinstance(params, dict) else None
    return IBKRScannerParamsResponse(state="available", detail=None, categories=categories or [])


@router.post(
    "/scanner/run",
    response_model=IBKRScannerRunResponse,
    operation_id="run_ibkr_scanner",
    summary="Run an IBKR market scan, or report why the scanner is unavailable",
    responses={429: {"model": ErrorDetail, "description": "Scanner run rate limit (1 request/second) exceeded"}},
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
    otherwise-available* scanner, so it's surfaced as `429`, not folded into `state`.
    """
    if provider is None:
        return IBKRScannerRunResponse(state="disabled", detail=_DISABLED_DETAIL, results=None)

    try:
        results = provider.run_scanner(body.scan_config)
    except IBKRRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except IBKRUnavailableError:
        status = provider.get_gateway_status()
        return IBKRScannerRunResponse(state=status.state, detail=status.detail, results=None)

    return IBKRScannerRunResponse(
        state="available",
        detail=None,
        results=[
            IBKRScannerResultOut(conid=r.conid, symbol=r.symbol, company_name=r.company_name, rank=r.rank)
            for r in results
        ],
    )
