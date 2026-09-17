"""Pydantic request/response models mirroring docs/architecture/API.md.

This module is the source of truth FastAPI generates /openapi.json from; the
frontend's api/types.ts should be generated from that schema, not hand-typed
(see docs/architecture/Frontend.md §5). Field descriptions here are what make
the generated OpenAPI schema self-explanatory — see CLAUDE.md's API
documentation standard.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Signal = Literal["BUY", "SELL", "HOLD"]
ConfidenceBand = Literal["Low", "Medium", "High"]
Interval = Literal["daily", "weekly"]
Trend = Literal["BULLISH", "BEARISH", "NEUTRAL"]
Impulse = Literal["GREEN", "RED", "BLUE"]


# --- /api/stocks/{ticker}/history ---------------------------------------


class OHLCVBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class HistoryResponse(BaseModel):
    ticker: str
    interval: Interval
    bars: list[OHLCVBar]


# --- /api/stocks/{ticker}/analysis --------------------------------------


class TideScreen(BaseModel):
    trend: Trend = Field(description="Screen 1 output (docs/Analyse.md §2). NEUTRAL when weekly MACD-Histogram slope and the 13/26-week EMA relationship disagree.")
    weekly_macd_histogram_slope: Literal["rising", "falling", "flat"]


class WaveScreen(BaseModel):
    stochastic_k: float = Field(description="Stochastic %K (5,3,3). Values below 30 are oversold, above 70 are overbought (docs/Analyse.md §4).")
    force_index_2ema: float = Field(description="Force Index, 2-period EMA smoothing (entry-timing variant, not the 13-period trend-confirmation one).")
    state: str = Field(description="Human-readable wave state, e.g. 'OVERSOLD_PULLBACK' — evaluated against the tide direction, not in isolation (docs/Analyse.md §2).")


class TriggerScreen(BaseModel):
    fired: bool = Field(description="Whether Screen 3 confirmed price has resumed the tide's direction.")
    reference: str = Field(description="Which trigger rule fired, e.g. 'close_above_prior_high'.")


class Screens(BaseModel):
    tide: TideScreen
    impulse: Impulse = Field(description="Impulse System gate (docs/Analyse.md §3). RED blocks fresh BUY signals, GREEN blocks fresh SELL signals.")
    wave: WaveScreen
    trigger: TriggerScreen


class ConfidenceBreakdownItem(BaseModel):
    component: str = Field(description="One of the five weighted components from docs/Analyse.md §6, e.g. 'tide_alignment'.")
    weight: float = Field(description="This component's fixed weight (0-1); all five weights sum to 1.0.")
    score: float = Field(description="How strongly this component supports the signal (0-1), before weighting.")


class Indicators(BaseModel):
    ema_13: float
    ema_26: float
    macd_histogram: float
    bull_power: float = Field(description="Elder-Ray Bull Power = High - EMA(13).")
    bear_power: float = Field(description="Elder-Ray Bear Power = Low - EMA(13).")


class AnalysisResponse(BaseModel):
    ticker: str
    as_of: date
    signal: Signal
    confidence: int = Field(description="0-100 weighted composite score (docs/Analyse.md §6). Not a statistical probability.")
    confidence_band: ConfidenceBand = Field(description="Low <40, Medium 40-70, High >70.")
    screens: Screens
    confidence_breakdown: list[ConfidenceBreakdownItem] = Field(description="Per-component scores behind `confidence`, so the signal is auditable rather than a bare number.")
    indicators: Indicators


# --- /api/portfolio -------------------------------------------------------


class Equity(BaseModel):
    cash: float
    positions_value: float = Field(description="Sum of quantity x current_price across all positions (mark-to-market, not cost basis).")
    total: float = Field(description="cash + positions_value.")


class PositionOut(BaseModel):
    id: str
    ticker: str
    quantity: float
    avg_cost_basis: float
    entry_date: date
    current_price: float | None = Field(default=None, description="Null only if the latest price fetch for this ticker failed.")
    unrealized_pnl_pct: float | None = Field(default=None, description="(current_price - avg_cost_basis) / avg_cost_basis, as a percentage. Null under the same condition as current_price.")


class PortfolioResponse(BaseModel):
    equity: Equity
    positions: list[PositionOut]


class PositionIn(BaseModel):
    ticker: str = Field(min_length=1, description="Stock ticker symbol, normalized to uppercase (leading/trailing whitespace is stripped). Adding a ticker that's already held merges into the existing position (quantity-weighted average cost basis) rather than creating a duplicate row — see the api-portfolio-add-position task's decisions.")
    quantity: float = Field(gt=0, allow_inf_nan=False, description="Number of shares being added. Must be a positive, finite number (Infinity/NaN are rejected) — this endpoint only adds to a position; use DELETE /api/portfolio/positions/{id} to remove one.")
    avg_cost_basis: float = Field(gt=0, allow_inf_nan=False, description="Price paid per share for this lot. On merge with an existing position, this is blended into a quantity-weighted average, not overwritten. Must be a positive, finite number (Infinity/NaN are rejected).")
    entry_date: date = Field(description="Date this lot was purchased. On merge with an existing position, the earlier of the two entry dates is kept.")

    @field_validator("ticker")
    @classmethod
    def _strip_and_require_non_blank_ticker(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("ticker must not be blank or whitespace-only")
        return stripped


# --- /api/portfolio/risk ---------------------------------------------------


class RiskPosition(BaseModel):
    id: str
    ticker: str
    protective_stop: float = Field(description="Recent swing low minus a volatility buffer (SafeZone concept, docs/Analyse.md §7).")
    position_risk_pct: float = Field(description="Fraction of current account equity lost if this position hits its protective_stop (the 2% rule).")
    two_percent_rule_breached: bool
    exit_flags: list[str] = Field(description="Risk-driven exit reasons, e.g. 'stop_hit', 'tide_flipped_bearish' (docs/Analyse.md §7). Independent of this stock's fresh entry signal — can be non-empty even when /analysis says HOLD.")


class RiskResponse(BaseModel):
    total_open_risk_pct: float = Field(description="Sum of position_risk_pct across all positions (the 6% rule).")
    six_percent_rule_breached: bool
    positions: list[RiskPosition]


# --- shared error shape (FastAPI default, documented for clarity) ---------


class ErrorDetail(BaseModel):
    detail: str
