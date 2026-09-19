from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class ExitReason(StrEnum):
    """Why a position was closed, per Elder's own taxonomy (docs/ideas.md's ch. 51 cross-check;
    docs/Analyse.md §7) -- recorded per row in ``ClosedTradeORM`` (app/db/models.py) so the
    future ``backend-trade-grading`` task's buy/sell/trade-grade formulas and a trade-journal
    frontend page have this to work with, in addition to this task's own use (the 6% Rule's
    realized-losses-this-month component, ``app.portfolio.risk.realized_losses_pct``).

    ``UNSPECIFIED`` is not one of Elder's own tags -- it's this app's own default for a trade
    closed via ``DELETE /api/portfolio/positions/{id}`` without an explicit ``exit_reason``
    query param, since that endpoint has no way to *know* why the user is closing the position
    unless they say so (there's no target-price/stop-order concept tracked anywhere in this
    app to infer it from) -- see the backend-trade-history-table task's `decisions` entry.
    """

    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    REACHED_VALUE_ZONE = "reached_value_zone"
    GOING_NOWHERE = "going_nowhere"
    STARTING_TO_TURN = "starting_to_turn"
    COULDNT_STAND_THE_PAIN = "couldnt_stand_the_pain"
    RECOGNIZED_JUNK_TRADE_AFTER_ENTRY = "recognized_junk_trade_after_entry"
    UNSPECIFIED = "unspecified"


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
