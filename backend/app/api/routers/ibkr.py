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

`GET /api/ibkr/portfolio-preview` + `POST /api/ibkr/portfolio-preload`
(docs/tasks/backend-ibkr-portfolio-preload.json) are the user-requested "preload my real IBKR
positions into this app" feature: the preview route is a read-only look at which of the
connected account's current equity positions (`IBKRProvider.get_account_positions`) would be
importable vs. conflicting with an already-held local ticker, and the preload route actually
imports every non-conflicting one, re-checking conflicts against the `positions` table's
CURRENT state (so a ticker the caller just deleted via `DELETE /api/portfolio/positions/{id}`
is treated as available) -- see that task's `decisions` entry for the full requirement
breakdown and every judgment call this pair of routes makes. Both reuse `/status`'s exact
`state`-on-a-normal-200 availability pattern, same as the scanner/breadth routes above. Neither
route ever goes through `POST /api/portfolio/positions`'s same-ticker-merge path -- a
still-conflicting ticker is always skipped entirely, never merged/updated.
"""

import logging
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import get_ibkr_provider
from app.api.schemas import (
    ROLLING_WINDOW_DAYS,
    ErrorDetail,
    IBKRBreadthSnapshotRequest,
    IBKRBreadthSnapshotResponse,
    IBKRGatewayState,
    IBKRPortfolioPreloadImportedPositionOut,
    IBKRPortfolioPreloadResponse,
    IBKRPortfolioPreviewPositionOut,
    IBKRPortfolioPreviewResponse,
    IBKRScannerParamsResponse,
    IBKRScannerResultOut,
    IBKRScannerRunRequest,
    IBKRScannerRunResponse,
    IBKRStatusResponse,
)
from app.data.ibkr_provider import (
    GatewayStatus,
    IBKRAccountPosition,
    IBKRProvider,
    IBKRRateLimitedError,
    IBKRUnavailableError,
)
from app.db.models import IBKRBreadthSnapshotORM, PositionORM
from app.db.session import get_db
from app.time_utils import today, utcnow

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"])
logger = logging.getLogger(__name__)

_DISABLED_DETAIL = "IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."

# Shared 429 `responses={}` entry for `run_ibkr_scanner` and
# `record_ibkr_breadth_snapshot` -- both eventually call `IBKRProvider.run_scanner`, the
# only method the client-side rate limit in `_rate_limited_http_exception` applies to, so
# both routes' 429s carry the exact same header contract. Previously duplicated verbatim
# between the two routes' `responses={}` dicts, which let them silently drift out of sync
# (see this task's `decisions` entry); factored out here so there's exactly one place to
# change. `headers["Retry-After"]["required"]` is `True` because
# `_rate_limited_http_exception` unconditionally sets this header on every 429 it builds --
# there's no code path where a caller gets a 429 from these routes without it -- so the
# generated frontend type is `"Retry-After": number`, not the misleadingly optional
# `"Retry-After"?: number`.
_RETRY_AFTER_429_RESPONSE: dict[str, object] = {
    "model": ErrorDetail,
    "description": "Scanner run rate limit (1 request/second) exceeded -- retry after the "
    "number of seconds in the `Retry-After` response header",
    "headers": {
        "Retry-After": {
            "description": "Number of seconds to wait before retrying the scanner run",
            "required": True,
            "schema": {"type": "integer"},
        },
    },
}


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


def _resolve_ibkr_call_unavailable(provider: IBKRProvider, exc: IBKRUnavailableError) -> GatewayStatus:
    """Shared `except IBKRUnavailableError` handling for every route in this module that
    makes a data-fetching call beyond the initial availability check (originally just the
    two scanner routes -- see `backend-ibkr-portfolio-preload`'s `decisions` entry for why
    this was generalized/renamed from `_resolve_scanner_unavailable` rather than
    duplicated a third and fourth time for the portfolio-preview/preload routes below).

    `IBKRUnavailableError` is raised for two genuinely different reasons that share one
    exception type (see `IBKRProvider._request`/`_require_available`): the gateway/session
    itself isn't `available` (checked *before* the underlying call is even attempted), or
    that specific call itself failed transiently against a gateway that otherwise is
    `available` (a non-200 response, transport error, or unparseable body from the
    specific IBKR endpoint that call hits). A fresh `get_gateway_status()` call only
    re-checks the former (it hits the unrelated `/iserver/auth/status` endpoint) -- so on
    the latter, that fresh check still reports `available`, and returning
    `state: "available"` with the response's own data field(s) left `null` would violate
    that schema's own documented "non-null iff `state` == 'available'" invariant (see this
    task's `review` finding). Raises `HTTPException(503)` in exactly that disagreeing case
    (the standard "service temporarily unavailable" status for a transient, single-call
    failure -- distinct from `429`'s "you're calling too fast" and from the `state`
    values' "this feature isn't usable at all right now"); otherwise returns the resolved
    `GatewayStatus` for the caller to build its normal `state`-based response from.
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
    see `_resolve_ibkr_call_unavailable` -- and is raised as a `503` instead.
    """
    if provider is None:
        return IBKRScannerParamsResponse(state="disabled", detail=_DISABLED_DETAIL, categories=None)

    try:
        params = provider.get_scanner_params()
    except IBKRUnavailableError as exc:
        status = _resolve_ibkr_call_unavailable(provider, exc)
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
        429: _RETRY_AFTER_429_RESPONSE,
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
    otherwise-`available` gateway (see `_resolve_ibkr_call_unavailable`) is likewise surfaced as
    a `503`, not folded into `state`.
    """
    if provider is None:
        return IBKRScannerRunResponse(state="disabled", detail=_DISABLED_DETAIL, results=None)

    try:
        results = provider.run_scanner(body.scan_config)
    except IBKRRateLimitedError as exc:
        raise _rate_limited_http_exception(exc) from exc
    except IBKRUnavailableError as exc:
        status = _resolve_ibkr_call_unavailable(provider, exc)
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
        429: _RETRY_AFTER_429_RESPONSE,
        503: {
            "model": ErrorDetail,
            "description": "Either the scanner-run call itself failed transiently (not a "
            "gateway/session unavailability -- see GET /api/ibkr/status for that), or a "
            "concurrent-write conflict was raised on this row's commit but no same-key row "
            "was actually found afterwards (see this task's `decisions` entry) -- both "
            "transient, safe to retry.",
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
    request for this `series_key`), since a cache hit never calls the scanner at all. A `503`
    is also raised (distinct from the concurrent-insert fallback below succeeding silently)
    if a concurrent-write conflict is caught on this row's own commit but no same-key row
    actually exists afterwards -- see this task's `decisions` entry.
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
            status = _resolve_ibkr_call_unavailable(provider, exc)
            return _unavailable_breadth_response(body.series_key, status.state, status.detail)

        row = IBKRBreadthSnapshotORM(
            series_key=body.series_key,
            snapshot_date=snapshot_date,
            count=len(results),
            recorded_at=utcnow(),
        )
        db.add(row)
        try:
            db.commit()
        except (IntegrityError, OperationalError) as exc:
            # Two concurrent first-of-the-day requests for the same (series_key,
            # snapshot_date) can both see `row is None` above and both attempt to insert
            # it, so the loser's commit hits the composite primary key (IntegrityError) --
            # or, under SQLite's default file-level locking (no WAL mode/busy_timeout
            # configured, app/db/session.py), OperationalError ("database is locked").
            # Same category of race already caught this way for OHLCVCacheORM's
            # `_upsert`/`_upsert_extended` (app/data/cache.py) -- but unlike that cache
            # (which can safely discard the loser's write and still return the frame it
            # fetched, independent of the DB), this route's response fields are read from
            # the persisted row itself, so the loser must roll back its own failed insert
            # and fall back to reading the winner's already-committed row instead of just
            # swallowing the error. See this task's `decisions` entry.
            #
            # IntegrityError's scope is verified narrow: this table's composite PK is its
            # only constraint (app/db/models.py), so an IntegrityError here can only mean
            # the same-key race above. OperationalError's scope is *not* pinned down the
            # same way -- SQLite's whole-file write locking can raise "database is locked"
            # from *any* concurrent write anywhere in the file, not only a race on this
            # exact (series_key, snapshot_date) -- see app/data/cache.py's `_upsert`
            # OperationalError branch for the identical caveat on the identical exception
            # pair. So `db.get(...)` below may legitimately find no winner row even after
            # a genuine OperationalError; that's handled explicitly rather than assumed
            # away, since (unlike `_upsert`, which can safely discard a wasted write) this
            # route has no independently-fetched value to fall back to if no row exists.
            db.rollback()
            winner = db.get(IBKRBreadthSnapshotORM, (body.series_key, snapshot_date))
            if winner is None:
                logger.warning(
                    "Concurrent-write conflict recording breadth snapshot for "
                    "series_key=%r date=%s, but no same-key row was found afterwards -- "
                    "likely an unrelated SQLite lock contention, not a race on this key. "
                    "(%s: %s)",
                    body.series_key,
                    snapshot_date,
                    type(exc).__name__,
                    exc,
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Transient write conflict recording breadth snapshot for "
                        f"series_key={body.series_key!r}; retry."
                    ),
                ) from exc
            logger.warning(
                "Concurrent breadth-snapshot population for series_key=%r date=%s raced "
                "this insert; falling back to the concurrently-committed row. (%s: %s)",
                body.series_key,
                snapshot_date,
                type(exc).__name__,
                exc,
            )
            row = winner
        else:
            db.refresh(row)

    # Single query (not `func.count()` plus a separately `LIMIT`-ed query) for both
    # `days_recorded` and the rolling sums below: all of this series' recorded `count`
    # values, most recent first. Fetches this series' full history rather than bounding it
    # to `max(ROLLING_WINDOW_DAYS)` rows -- a deliberate trade-off (one round trip instead
    # of two, at the cost of loading more rows than the rolling sums themselves need) that's
    # cheap here since this route persists at most one row per series per calendar day. See
    # this task's `decisions` entry.
    recorded_counts = [
        c
        for (c,) in db.query(IBKRBreadthSnapshotORM.count)
        .filter(IBKRBreadthSnapshotORM.series_key == body.series_key)
        .order_by(IBKRBreadthSnapshotORM.snapshot_date.desc())
        .all()
    ]
    days_recorded = len(recorded_counts)
    window_5d, window_20d = ROLLING_WINDOW_DAYS

    return IBKRBreadthSnapshotResponse(
        state="available",
        detail=None,
        series_key=body.series_key,
        snapshot_date=snapshot_date,
        count=row.count,
        days_recorded=days_recorded,
        rolling_5d=sum(recorded_counts[:window_5d]) if days_recorded >= window_5d else None,
        rolling_20d=sum(recorded_counts[:window_20d]) if days_recorded >= window_20d else None,
    )


# --- GET /api/ibkr/portfolio-preview, POST /api/ibkr/portfolio-preload -----

# Prefixed to every imported position's `entry_notes` (backend-ibkr-portfolio-preload's
# `decisions` entry): IBKR's positions endpoint has no notion of "when was this opened",
# so `entry_date` below is always today's date, not the real purchase date -- silently
# leaving that undocumented on the row itself would be misleading the next time this
# position is viewed (e.g. in a trade-duration or profit-target calculation that assumes
# `entry_date` is meaningful). Not attached to `strategy` -- see this task's `decisions`
# entry for why that field is left null instead.
_IBKR_IMPORT_ENTRY_NOTE_TEMPLATE = (
    "Imported from IBKR account positions on {entry_date}. entry_date reflects the "
    "import date, not the original purchase date -- IBKR's positions endpoint does not "
    "report when a position was opened."
)


def _existing_position_tickers(db: Session) -> set[str]:
    """Every ticker currently held locally (`app.db.models.PositionORM.ticker`, already
    stored uppercase -- see `app.api.routers.portfolio.add_position`) -- queried fresh on
    every call to `get_ibkr_portfolio_preview`/`preload_ibkr_portfolio` so both routes
    always see the DB's CURRENT state, not a stale snapshot (requirement 5's ordering:
    a ticker deleted via `DELETE /api/portfolio/positions/{id}` a moment before either of
    these routes runs must be treated as already gone, not as a conflict)."""
    return {ticker for (ticker,) in db.query(PositionORM.ticker).all()}


def _valid_import_candidates(positions: list[IBKRAccountPosition]) -> list[IBKRAccountPosition]:
    """Positions from `IBKRProvider.get_account_positions()` that carry everything a
    `PositionORM` row actually needs: `IBKRAccountPosition.ticker`/`.quantity` are already
    guaranteed non-None/strictly-positive by `_parse_account_positions`, but `.avg_cost`
    is independently nullable there (see that dataclass's own docstring) -- this filter is
    what excludes a position with no known cost basis from being shown as an importable
    candidate at all, on both the preview and the preload routes (so a caller never sees a
    position in `positions`/`imported` that the other route would silently refuse to
    import). See this task's `decisions` entry for why "no cost basis, no import" was
    chosen over inventing a placeholder cost basis."""
    return [
        p
        for p in positions
        if p.avg_cost is not None and math.isfinite(p.avg_cost) and p.avg_cost > 0
    ]


@router.get(
    "/portfolio-preview",
    response_model=IBKRPortfolioPreviewResponse,
    operation_id="get_ibkr_portfolio_preview",
    summary="Preview which of the IBKR account's current positions would be imported, and which conflict with an existing local position",
    responses={
        503: {
            "model": ErrorDetail,
            "description": "The account-positions fetch itself failed transiently (not a "
            "gateway/session unavailability -- see GET /api/ibkr/status for that)",
        }
    },
)
def get_ibkr_portfolio_preview(
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
    db: Session = Depends(get_db),
) -> IBKRPortfolioPreviewResponse:
    """Read-only preview for the "preload my IBKR positions" feature
    (docs/tasks/backend-ibkr-portfolio-preload.json, requirements 1-2): fetches the
    connected IBKR account's current equity positions
    (`IBKRProvider.get_account_positions`) and flags each one with whether its ticker
    already exists in the local `positions` table right now. Makes no DB writes at all --
    a caller can call this as many times as it likes while deciding which existing local
    positions (if any) to delete before calling `POST /api/ibkr/portfolio-preload`.

    'disabled'/`gateway_unreachable`/`not_authenticated` states behave exactly like
    `GET /api/ibkr/scanner/params` -- a normal `200` response, never an HTTP error, with
    `positions` left null. A transient failure of the account-positions fetch itself
    against an otherwise-`available` gateway is surfaced as `503`, same convention as
    every other IBKR data-fetching route in this module (see
    `_resolve_ibkr_call_unavailable`).

    Only positions `IBKRProvider.get_account_positions()` could actually resolve to a
    clean ticker AND a usable cost basis appear here at all (`_valid_import_candidates`) --
    the same filter `POST /api/ibkr/portfolio-preload` applies before importing, so a
    caller never sees a position previewed here that the preload route would then
    silently skip for an unrelated reason.
    """
    if provider is None:
        return IBKRPortfolioPreviewResponse(state="disabled", detail=_DISABLED_DETAIL, positions=None)

    try:
        account_positions = provider.get_account_positions()
    except IBKRUnavailableError as exc:
        status = _resolve_ibkr_call_unavailable(provider, exc)
        return IBKRPortfolioPreviewResponse(state=status.state, detail=status.detail, positions=None)

    existing_tickers = _existing_position_tickers(db)
    candidates = _valid_import_candidates(account_positions)

    return IBKRPortfolioPreviewResponse(
        state="available",
        detail=None,
        positions=[
            IBKRPortfolioPreviewPositionOut(
                conid=p.conid,
                ticker=p.ticker,
                quantity=p.quantity,
                avg_cost=p.avg_cost,
                conflicts_with_existing_position=p.ticker in existing_tickers,
            )
            for p in candidates
        ],
    )


@router.post(
    "/portfolio-preload",
    response_model=IBKRPortfolioPreloadResponse,
    operation_id="preload_ibkr_portfolio",
    summary="Import every current IBKR account position that doesn't conflict with an existing local position",
    responses={
        503: {
            "model": ErrorDetail,
            "description": "The account-positions fetch itself failed transiently (not a "
            "gateway/session unavailability -- see GET /api/ibkr/status for that)",
        }
    },
)
def preload_ibkr_portfolio(
    provider: IBKRProvider | None = Depends(get_ibkr_provider),
    db: Session = Depends(get_db),
) -> IBKRPortfolioPreloadResponse:
    """Actually imports the connected IBKR account's current equity positions into the
    local `positions` table (docs/tasks/backend-ibkr-portfolio-preload.json, requirements
    3 and 5) -- the write half of the preview/preload pair above.

    Re-fetches IBKR positions and re-checks each one's ticker against the `positions`
    table's CURRENT state at the moment this endpoint runs (`_existing_position_tickers`),
    NOT whatever an earlier `GET /api/ibkr/portfolio-preview` call happened to see -- so a
    ticker the caller deleted via `DELETE /api/portfolio/positions/{id}` in between the two
    calls is correctly treated as no-longer-conflicting (requirement 5's exact ordering:
    "the chosen deletions must be applied BEFORE that conflict check runs"). A ticker still
    present in the DB at this point is skipped entirely and reported in
    `skipped_conflicting_tickers` -- this NEVER goes through `POST
    /api/portfolio/positions`'s same-ticker-merge path (requirement 3): a still-held local
    position is left completely untouched, not updated/combined with the IBKR data in any
    way. Two fetched IBKR positions resolving to the same ticker (an edge case
    `_parse_account_positions`'s equity-only filtering doesn't rule out, e.g. the same
    company held under the same symbol text in more than one sub-account) are likewise
    de-duplicated within this same call -- only the first is imported, and every
    subsequent same-ticker entry is reported in `skipped_conflicting_tickers` too, since
    `PositionORM.ticker` has a uniqueness constraint that would otherwise fail the second
    insert outright. See this task's `decisions` entry.

    `entry_date` on every imported position is always today's date (see
    `IBKRPortfolioPreloadImportedPositionOut.entry_date`'s own description for why), and
    `entry_notes` records that fact explicitly so it's visible later rather than silently
    misleading (`_IBKR_IMPORT_ENTRY_NOTE_TEMPLATE`). `strategy` is always null -- IBKR's
    positions response carries nothing this app could map onto a personal named strategy
    tag, and guessing one would misrepresent the trader's own intent. See this task's
    `decisions` entry.

    'disabled'/`gateway_unreachable`/`not_authenticated` states behave exactly like
    `GET /api/ibkr/portfolio-preview` -- a normal `200` response, never an HTTP error, with
    `imported`/`skipped_conflicting_tickers` both left null and nothing written to the DB.
    A transient failure of the account-positions fetch itself is surfaced as `503`, same
    convention as every other IBKR data-fetching route in this module.
    """
    if provider is None:
        return IBKRPortfolioPreloadResponse(
            state="disabled", detail=_DISABLED_DETAIL, imported=None, skipped_conflicting_tickers=None
        )

    try:
        account_positions = provider.get_account_positions()
    except IBKRUnavailableError as exc:
        status = _resolve_ibkr_call_unavailable(provider, exc)
        return IBKRPortfolioPreloadResponse(
            state=status.state, detail=status.detail, imported=None, skipped_conflicting_tickers=None
        )

    existing_tickers = _existing_position_tickers(db)
    candidates = _valid_import_candidates(account_positions)
    entry_date = today()
    entry_notes = _IBKR_IMPORT_ENTRY_NOTE_TEMPLATE.format(entry_date=entry_date)

    imported: list[IBKRPortfolioPreloadImportedPositionOut] = []
    skipped: list[str] = []
    seen_this_batch: set[str] = set()
    for p in candidates:
        if p.ticker in existing_tickers or p.ticker in seen_this_batch:
            skipped.append(p.ticker)
            continue
        seen_this_batch.add(p.ticker)
        # _valid_import_candidates already filtered out a None/non-finite/non-positive
        # avg_cost -- narrowed explicitly for mypy, matching this codebase's existing
        # assert-narrow convention (e.g. app.api.day_trader_signal).
        assert p.avg_cost is not None
        db.add(
            PositionORM(
                id=f"pos_{uuid.uuid4().hex[:12]}",
                ticker=p.ticker,
                quantity=p.quantity,
                avg_cost_basis=p.avg_cost,
                entry_date=entry_date,
                entry_notes=entry_notes,
                strategy=None,
            )
        )
        imported.append(
            IBKRPortfolioPreloadImportedPositionOut(
                ticker=p.ticker,
                quantity=p.quantity,
                avg_cost_basis=p.avg_cost,
                entry_date=entry_date,
            )
        )
    db.commit()

    return IBKRPortfolioPreloadResponse(
        state="available",
        detail=None,
        imported=imported,
        skipped_conflicting_tickers=skipped,
    )
