from fastapi import FastAPI

from app.api.routers import portfolio, stocks

app = FastAPI(
    title="fintrade",
    version="0.1.0",
    description="Stock and portfolio signal analysis API implementing Dr. Alexander Elder's Triple Screen methodology (see docs/Analyse.md).",
)

app.include_router(stocks.router)
app.include_router(portfolio.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
