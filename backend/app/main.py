import math
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routers import portfolio, stocks
from app.db.models import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Stopgap until the db-migrations task wires up Alembic (docs/tasks/db-migrations.json):
    # create_all is idempotent (no-op against tables that already exist) so it's safe to run
    # on every startup and won't conflict with a later `alembic upgrade head`.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="fintrade",
    version="0.1.0",
    description="Stock and portfolio signal analysis API implementing Dr. Alexander Elder's Triple Screen methodology (see docs/Analyse.md).",
    lifespan=lifespan,
)

app.include_router(stocks.router)
app.include_router(portfolio.router)


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
