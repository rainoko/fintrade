from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
