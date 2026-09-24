import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.dependencies import get_ibkr_provider
from app.api.routers import cftc, homework, ibkr, portfolio, settings, stocks, watchlist
from app.data.ibkr_provider import IBKRProvider
from app.db.models import Base
from app.db.session import engine

logger = logging.getLogger(__name__)

# docs/architecture/Backend.md §8: "keep the session alive with a periodic GET /tickle
# call roughly once a minute". Picked 45s rather than exactly 60s for a safety margin
# below that "roughly" figure -- docs/ideas.md's own research note on this gap warns
# "IBKR's session timeout is short" without pinning an exact number, and unlike
# `/iserver/scanner/params`/`/iserver/scanner/run` (documented, enforced rate limits of
# 1 req/15min and 1 req/sec respectively), IBKR's docs don't document any rate limit on
# `/tickle` itself -- so polling somewhat more often than the letter of "roughly once a
# minute" costs nothing while buying margin against a shorter-than-expected timeout.
# See this task's `decisions` entry.
_IBKR_TICKLE_INTERVAL_SECONDS = 45.0


async def _ibkr_tickle_loop(provider: IBKRProvider) -> None:
    """Background keep-alive loop for as long as the app process runs: sleeps
    `_IBKR_TICKLE_INTERVAL_SECONDS`, then calls `IBKRProvider.tickle()` in a worker
    thread (`asyncio.to_thread`, since `tickle()`'s underlying HTTP call is a blocking
    `httpx.Client` request that would otherwise stall the event loop -- and with it every
    other in-flight request -- for the duration of the round trip). A failed tickle
    (gateway down, or a session that's already expired) is logged and the loop keeps
    running rather than stopping: `GET /api/ibkr/status`
    (`backend-ibkr-status-endpoint`) already exists for a caller to observe the resulting
    `not_authenticated`/`gateway_unreachable` state, so this loop's only job is to keep
    pinging, not to raise an alert of its own.
    """
    while True:
        await asyncio.sleep(_IBKR_TICKLE_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(provider.tickle)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see rationale below
            # `provider.tickle()`'s three raise sites (`IBKRProvider._request`) are
            # exhaustively `IBKRUnavailableError` today, but narrowing this catch to that
            # one type is a latent trap: if `tickle()` ever raised anything else, this
            # loop would exit with that exception stored on the task, `tickle_task.cancel()`
            # in `lifespan()`'s `finally` would become a no-op against an already-done
            # task, and `await tickle_task` there (inside
            # `contextlib.suppress(asyncio.CancelledError)`) would re-raise the original
            # exception straight out of `lifespan()`'s own `finally` block, disrupting app
            # shutdown -- not just silently pausing the keep-alive the way a caught
            # `IBKRUnavailableError` does. `Exception` (not `BaseException`) deliberately
            # still lets a real `asyncio.CancelledError` (a `BaseException` since Python
            # 3.8) propagate through untouched, so cancellation at shutdown still works.
            logger.warning("IBKR /tickle keep-alive call failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Alembic (app/db/migrations/, see README.md's "Database migrations" section) is now the
    # source of truth for schema changes -- this call is a convenience bootstrap only, so a
    # brand-new dev/test database works immediately without requiring `alembic upgrade head`
    # first. create_all is idempotent (no-op against tables that already exist), so it never
    # conflicts with a database Alembic has already migrated.
    Base.metadata.create_all(bind=engine)

    # `next(get_ibkr_provider())` reuses that dependency's own `Settings.ibkr_enabled`
    # gate and process-wide singleton (app.api.dependencies) rather than duplicating
    # either here -- it yields `None` (no task started, no gateway call ever made) when
    # IBKR isn't enabled, which is every environment without a locally-running,
    # authenticated IB Gateway (the default, and every test in this suite's own
    # environment). `get_ibkr_provider` has no cleanup logic after its single `yield` in
    # either branch, so calling `next()` once without ever closing the generator loses
    # nothing.
    tickle_task: asyncio.Task[None] | None = None
    provider = next(get_ibkr_provider())
    if provider is not None:
        tickle_task = asyncio.create_task(_ibkr_tickle_loop(provider))

    try:
        yield
    finally:
        if tickle_task is not None:
            tickle_task.cancel()
            # `await tickle_task` here returns promptly even if `_ibkr_tickle_loop` was
            # cancelled while mid-`await asyncio.to_thread(provider.tickle)` (an HTTP
            # request already dispatched to a worker thread): `asyncio.to_thread` awaits a
            # plain `asyncio.Future` wrapping the executor's `concurrent.futures.Future`,
            # and a plain `Future.cancel()` marks itself cancelled immediately regardless
            # of whether the underlying thread-pool work can actually be stopped, so
            # `CancelledError` propagates into this `await` right away rather than
            # blocking on the in-flight call. The worker thread itself is not
            # interrupted -- it keeps running `provider.tickle()` to completion in the
            # background, orphaned and discarded, which is harmless here (no result is
            # ever read back from it). Verified with a real-timing repro (see the
            # `decisions` on task `backend-ibkr-tickle-keepalive-followups` -- resolve
            # its current file location via docs/tasks/index.json rather than assuming
            # a literal path, since its file location can change over its lifecycle)
            # rather than assumed.
            with contextlib.suppress(asyncio.CancelledError):
                await tickle_task


app = FastAPI(
    title="fintrade",
    version="0.1.0",
    description="Stock and portfolio signal analysis API implementing Dr. Alexander Elder's Triple Screen methodology (see docs/Analyse.md).",
    lifespan=lifespan,
)

app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(ibkr.router)
app.include_router(homework.router)
app.include_router(cftc.router)
app.include_router(settings.router)


def _drop_non_finite_floats(value: Any) -> Any:
    """Recursively replace inf/-inf/nan floats with their string form (e.g. "Infinity").

    Pydantic's `finite_number` validation error (raised by a `Field(allow_inf_nan=False)`
    constraint) echoes the client's raw rejected value back in its `input` field — e.g.
    `{"type": "finite_number", ..., "input": inf}`. Starlette's JSONResponse.render uses
    `json.dumps(..., allow_nan=False)`, so serializing that echoed value as-is raises an
    unhandled ValueError *inside the 422 error handler itself*, turning what should be a
    422 into a raw 500 — the same "reject bad input cleanly" goal the 422 was meant to
    satisfy, undone by echoing the bad input back verbatim. This walks the already-
    jsonable-encoded error body and neutralizes exactly that case before responding.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _drop_non_finite_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_drop_non_finite_floats(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Same 422 shape FastAPI's default handler produces, but with non-finite floats
    (Infinity/-Infinity/NaN) in the echoed invalid input sanitized so the response body
    itself is always valid JSON — see `_drop_non_finite_floats`."""
    return JSONResponse(
        status_code=422,
        content=_drop_non_finite_floats(jsonable_encoder({"detail": exc.errors()})),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
