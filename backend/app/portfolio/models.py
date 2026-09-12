from datetime import date

from pydantic import BaseModel


class Position(BaseModel):
    id: str
    ticker: str
    quantity: float
    avg_cost_basis: float
    entry_date: date
    current_price: float | None = None
    unrealized_pnl_pct: float | None = None


class Equity(BaseModel):
    cash: float
    positions_value: float
    total: float


class Account(BaseModel):
    equity: Equity
    positions: list[Position]
